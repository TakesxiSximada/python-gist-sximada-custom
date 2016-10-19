# -*- coding: utf-8 -*-
"""
Name:
    gist

Usage:
    gist list
    gist edit <id>
    gist description <id> <desc>
    gist info <id>
    gist fork <id>
    gist files <id>
    gist delete <ids> ...
    gist archive <id>
    gist content <id> [<filename>] [--decrypt]
    gist create <desc> [--public] [--encrypt] [FILES ...]
    gist clone <id> [<name>]
    gist version

Description:
    This program provides a command line interface for interacting with github
    gists.

Commands:
    create
        Create a new gist. A gist can be created in several ways. The content
        of the gist can be piped to the gist,

            $ echo "this is the content" | gist create "gist description"

        The gist can be created from an existing set of files,

            $ gist create "gist description" foo.txt bar.txt

        The gist can be created on the fly,

            $ gist create "gist description"

        which will open the users default editor.

    edit
        You can edit your gists directly with the 'edit' command. This command
        will clone the gist to a temporary directory and open up the default
        editor (defined by the EDITOR environment variable) to edit the files
        in the gist. When the editor is exited the user is prompted to commit
        the changes, which are then pushed back to the remote.

    fork
        Creates a fork of the specified gist.

    description
        Updates the description of a gist.

    list
        Returns a list of your gists. The gists are returned as,

            2b1823252e8433ef8682 - mathematical divagations
            a485ee9ddf6828d697be - notes on defenestration
            589071c7a02b1823252e + abecedarian pericombobulations

        The first column is the gists unique identifier; The second column
        indicates whether the gist is public ('+') or private ('-'); The third
        column is the description in the gist, which may be empty.

    clone
        Clones a gist to the current directory. This command will clone any
        gist based on its unique identifier (i.e. not just the users) to the
        current directory.

    delete
        Deletes the specified gist.

    files
        Returns a list of the files in the specified gist.

    archive
        Downloads the specified gist to a temporary directory and adds it to a
        tarball, which is then moved to the current directory.

    content
        Writes the content of each file in the specified gist to the terminal,
        e.g.

            $ gist content c971fca7997aed65ddc9
            foo.txt:
            this is foo


            bar.txt:
            this is bar


        For each file in the gist the first line is the name of the file
        followed by a colon, and then the content of that file is written to
        the terminal.

        If a filename is given, only the content of the specified filename
        will be printed.

           $ gist content de42344a4ecb6250d6cea00d9da6d83a file1
           content of file 1


    info
        This command provides a complete dump of the information about the gist
        as a JSON object. It is mostly useful for debugging.

    version
        Returns the current version of gist.

"""
import codecs
import fcntl
import locale
import logging
import os
import struct
import sys
import tempfile
import termios

import docopt
import gnupg
import simplejson as json

import gist

try:
    import configparser
except ImportError:
    import ConfigParser as configparser


logger = logging.getLogger('gist')


# We need to wrap stdout in order to properly handle piping uincode output
stream = sys.stdout.detach() if sys.version_info[0] > 2 else sys.stdout
encoding = locale.getpreferredencoding()
sys.stdout = codecs.getwriter(encoding)(stream)


class GistError(Exception):
    def __init__(self, msg):
        super(GistError, self).__init__(msg)
        self.msg = msg


def terminal_width():
    """Returns the terminal width

    Tries to determine the width of the terminal. If there is no terminal, then
    None is returned instead.

    """
    try:
        exitcode = fcntl.ioctl(
                0,
                termios.TIOCGWINSZ,
                struct.pack('HHHH', 0, 0, 0, 0))
        h, w, hp, wp = struct.unpack('HHHH', exitcode)
        return w
    except Exception:
        pass


def elide(txt, width=terminal_width()):
    """Elide the provided string

    The string is elided to the specified width, which defaults to the width of
    the terminal.

    Arguments:
        txt: the string to potentially elide
        width: the maximum permitted length of the string

    Returns:
        A string that is no longer than the specified width.

    """
    try:
        if len(txt) > width:
            return txt[:width - 3] + '...'
    except Exception:
        pass
    return txt


def alternative_editor(default):
    """Return the path to the 'alternatives' editor

    Argument:
        default: the default to use if the alternatives editor cannot be found.

    """
    if os.path.exists('/usr/bin/editor'):
        return '/usr/bin/editor'

    return default


def environment_editor(default):
    """Return the user specified environment default

    Argument:
        default: the default to use if the environment variable contains
                nothing useful.

    """
    editor = os.environ.get('EDITOR', '').strip()
    if editor != '':
        return editor

    return default


def configuration_editor(config, default):
    """Return the editor in the config file

    Argument:
        default: the default to use if there is no editor in the config

    """
    try:
        return config.get('gist', 'editor')
    except configparser.NoOptionError:
        return default


def alternative_config(default):
    """Return the path to the config file in .config directory

    Argument:
        default: the default to use if ~/.config/gist does not exist.

    """
    config_path = os.path.expanduser('~/.config/gist')
    if os.path.isfile(config_path):
        return config_path
    else:
        return default


def xdg_data_config(default):
    """Return the path to the config file in XDG user config directory

    Argument:
        default: the default to use if either the XDG_DATA_HOME environment is
            not set, or the XDG_DATA_HOME directory does not contain a 'gist'
            file.

    """
    config = os.environ.get('XDG_DATA_HOME', '').strip()
    if config != '':
        config_path = os.path.join(config, 'gist')
        if os.path.isfile(config_path):
            return config_path

    return default


def main(argv=sys.argv[1:], config=None):
    args = docopt.docopt(
            __doc__,
            argv=argv,
            version='gist-v{}'.format(gist.__version__),
            )

    # Read in the configuration file
    if config is None:
        config = configparser.ConfigParser()
        config_path = os.path.expanduser('~/.gist')
        config_path = alternative_config(config_path)
        config_path = xdg_data_config(config_path)
        with open(config_path) as fp:
            config.readfp(fp)

    # Setup logging
    fmt = "%(created).3f %(levelname)s[%(name)s] %(message)s"
    logging.basicConfig(format=fmt)

    try:
        log_level = config.get('gist', 'log-level').upper()
        logging.getLogger('gist').setLevel(log_level)
    except Exception:
        logging.getLogger('gist').setLevel(logging.ERROR)

    # Determine the editor to use
    editor = None
    editor = alternative_editor(editor)
    editor = environment_editor(editor)
    editor = configuration_editor(config, editor)

    if editor is None:
        raise ValueError('Unable to find an editor.')

    token = config.get('gist', 'token')
    gapi = gist.GistAPI(token=token, editor=editor)

    if args['list']:
        logger.debug(u'action: list')
        gists = gapi.list()
        for info in gists:
            public = '+' if info.public else '-'
            desc = '' if info.desc is None else info.desc
            line = u'{} {} {}'.format(info.id, public, desc)
            try:
                print(elide(line))
            except UnicodeEncodeError:
                logger.error('unable to write gist {}'.format(info.id))
        return

    if args['info']:
        gist_id = args['<id>']
        logger.debug(u'action: info')
        logger.debug(u'action: - {}'.format(gist_id))
        info = gapi.info(gist_id)
        print(json.dumps(info, indent=2))
        return

    if args['edit']:
        gist_id = args['<id>']
        logger.debug(u'action: edit')
        logger.debug(u'action: - {}'.format(gist_id))
        gapi.edit(gist_id)
        return

    if args['description']:
        gist_id = args['<id>']
        description = args['<desc>']
        logger.debug(u'action: description')
        logger.debug(u'action: - {}'.format(gist_id))
        logger.debug(u'action: - {}'.format(description))
        gapi.description(gist_id, description)
        return

    if args['fork']:
        gist_id = args['<id>']
        logger.debug(u'action: fork')
        logger.debug(u'action: - {}'.format(gist_id))
        info = gapi.fork(gist_id)
        return

    if args['clone']:
        gist_id = args['<id>']
        gist_name = args['<name>']
        logger.debug(u'action: clone')
        logger.debug(u'action: - {} as {}'.format(gist_id, gist_name))
        gapi.clone(gist_id, gist_name)
        return

    if args['content']:
        gist_id = args['<id>']
        logger.debug(u'action: content')
        logger.debug(u'action: - {}'.format(gist_id))

        content = gapi.content(gist_id)
        gist_file = content.get(args['<filename>'])

        if args['--decrypt']:
            if not config.has_option('gist', 'gnupg-homedir'):
                raise GistError('gnupg-homedir missing from config file')

            homedir = config.get('gist', 'gnupg-homedir')
            logger.debug(u'action: - {}'.format(homedir))

            gpg = gnupg.GPG(gnupghome=homedir, use_agent=True)
            if gist_file is not None:
                print(gpg.decrypt(gist_file).data.decode('utf-8'))
            else:
                for name, lines in content.items():
                    lines = gpg.decrypt(lines).data.decode('utf-8')
                    print(u'{} (decrypted):\n{}\n'.format(name, lines))

        else:
            if gist_file is not None:
                print(gist_file)
            else:
                for name, lines in content.items():
                    print(u'{}:\n{}\n'.format(name, lines))

        return

    if args['files']:
        gist_id = args['<id>']
        logger.debug(u'action: files')
        logger.debug(u'action: - {}'.format(gist_id))
        for f in gapi.files(gist_id):
            print(f)
        return

    if args['archive']:
        gist_id = args['<id>']
        logger.debug(u'action: archive')
        logger.debug(u'action: - {}'.format(gist_id))
        gapi.archive(gist_id)
        return

    if args['delete']:
        gist_ids = args['<ids>']
        logger.debug(u'action: delete')
        for gist_id in gist_ids:
            logger.debug(u'action: - {}'.format(gist_id))
            gapi.delete(gist_id)
        return

    if args['version']:
        logger.debug(u'action: version')
        print('v{}'.format(gist.__version__))
        return

    if args['create']:
        logger.debug('action: create')

        # If encryption is selected, perform an initial check to make sure that
        # it is possible before processing any data.
        if args['--encrypt']:
            if not config.has_option('gist', 'gnupg-homedir'):
                raise GistError('gnupg-homedir missing from config file')

            if not config.has_option('gist', 'gnupg-fingerprint'):
                raise GistError('gnupg-fingerprint missing from config file')

        # Retrieve the data to add to the gist
        if sys.stdin.isatty():
            if args['FILES']:
                logger.debug('action: - reading from files')
                files = {}
                for path in args['FILES']:
                    name = os.path.basename(path)
                    with open(path, 'rb') as fp:
                        files[name] = fp.read().decode('utf-8')
            else:
                logger.debug('action: - reading from editor')
                with tempfile.NamedTemporaryFile('wb+') as fp:
                    os.system('{} {}'.format(editor, fp.name))
                    fp.flush()
                    fp.seek(0)
                    files = {'file1.txt': fp.read().decode('utf-8')}

        else:
            logger.debug('action: - reading from stdin')
            files = {'file1.txt': sys.stdin.read()}

        description = args['<desc>']
        public = args['--public']

        # Encrypt the files or leave them unmodified
        if args['--encrypt']:
            logger.debug('action: - encrypting content')

            fingerprint = config.get('gist', 'gnupg-fingerprint')
            gnupghome = config.get('gist', 'gnupg-homedir')

            gpg = gnupg.GPG(gnupghome=gnupghome, use_agent=True)
            data = {}
            for k, v in files.items():
                cypher = gpg.encrypt(v.encode('utf-8'), fingerprint)
                content = cypher.data.decode('utf-8')
                data['{}.asc'.format(k)] = {'content': content}
        else:
            data = {k: {'content': v} for k, v in files.items()}

        print(gapi.create(description, data, public))
        return
