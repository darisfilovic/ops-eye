"""python3 -m opseye [--text] [--env FILE] [--out DIR] [--from-json FILE]"""

import sys

from .cli import main

sys.exit(main())
