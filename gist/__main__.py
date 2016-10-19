#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging

from . import (
    main,
    GistError,
    )

logger = logging.getLogger('gist')


if __name__ == "__main__":
    try:
        main()
    except GistError as e:
        sys.stderr.write(u"GIST: {}\n".format(e.msg))
        sys.stderr.flush()
        sys.exit(1)
    except Exception as e:
        logger.error(str(e))
        sys.exit(1)
