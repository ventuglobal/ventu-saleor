import os
import sys

import pytest

# Permite `import ventu_pagos.*`: agrega el dir de la app (padre del paquete).
_APP = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _APP not in sys.path:
    sys.path.insert(0, _APP)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """DB SQLite limpia por test, sin firma de webhooks (local)."""
    from ventu_pagos import config, db

    config.DATABASE_URL = f"sqlite:///{tmp_path}/ventu_pagos.db"
    config.VERIFY_SIGNATURE = False
    db.reset_engine()
    db.init_db()
    yield
    db.reset_engine()
