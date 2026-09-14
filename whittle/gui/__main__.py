"""`python -m whittle.gui`"""
from whittle.gui import platform as _platform

_platform.bootstrap()

from whittle.gui.app import main

raise SystemExit(main())
