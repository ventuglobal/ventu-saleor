"""Capa de persistencia de Ventu Pagos (SQLAlchemy).

Postgres en Railway (`DATABASE_URL`); SQLite por defecto en local/tests. El
engine y la fábrica de sesiones se construyen *perezosamente* para que los tests
puedan apuntar a otra URL antes del primer uso.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from . import config
from .models import Base

_engine = None
_SessionLocal: sessionmaker | None = None


def _normalize_url(url: str) -> str:
    # Railway/Heroku entregan `postgres://`; SQLAlchemy quiere `postgresql+psycopg://`.
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = _normalize_url(config.DATABASE_URL)
        kwargs: dict = {"pool_pre_ping": True, "future": True}
        if url.startswith("sqlite"):
            # SQLite en multihilo (uvicorn) necesita esto.
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)
    return _engine


def init_db() -> None:
    """Crea las tablas si no existen (idempotente). Se llama al arrancar."""
    Base.metadata.create_all(bind=get_engine())


def reset_engine() -> None:
    """Para tests: fuerza reconstruir el engine (p. ej. tras cambiar DATABASE_URL)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


@contextlib.contextmanager
def session_scope() -> Iterator[Session]:
    """Sesión transaccional: commit al salir ok, rollback ante excepción."""
    get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
