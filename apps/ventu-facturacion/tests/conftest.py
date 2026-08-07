import os
import sys

_APP = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _APP not in sys.path:
    sys.path.insert(0, _APP)
