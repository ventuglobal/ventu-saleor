import os
import sys

# Permite `import ventu.*` corriendo pytest desde cualquier rootdir:
# agrega el directorio `apps/` (padre del paquete `ventu`) al path.
_APPS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _APPS not in sys.path:
    sys.path.insert(0, _APPS)
