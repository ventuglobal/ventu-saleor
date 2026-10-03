"""Acceso a datos de Ventu Pagos: operaciones sobre `webpay_tx` y `app_config`.

Funciones pequeñas y explícitas (no un ORM repository genérico) para mantener los
handlers legibles y testeables con una DB SQLite en memoria/archivo.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from .db import session_scope
from .models import (
    STATUS_INITIALIZED,
    AppConfig,
    WebpayTx,
)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ───────────────────────────── webpay_tx ─────────────────────────────

def create_tx(
    *,
    token: str,
    buy_order: str,
    session_id: str,
    amount: int,
    saleor_transaction_id: str | None,
    checkout_id: str | None = None,
    channel_slug: str | None = None,
) -> None:
    with session_scope() as s:
        s.add(
            WebpayTx(
                token=token,
                buy_order=buy_order,
                session_id=session_id,
                amount=int(amount),
                saleor_transaction_id=saleor_transaction_id,
                checkout_id=checkout_id,
                channel_slug=channel_slug,
                status=STATUS_INITIALIZED,
            )
        )


def get_tx(token: str) -> WebpayTx | None:
    with session_scope() as s:
        return s.get(WebpayTx, token)


def get_tx_by_buy_order(buy_order: str) -> WebpayTx | None:
    with session_scope() as s:
        return s.scalar(select(WebpayTx).where(WebpayTx.buy_order == buy_order))


def close_tx(
    token: str,
    *,
    status: str,
    result: str,
    commit_response: dict | None = None,
    reported: bool = False,
) -> None:
    """Marca la tx con su resultado final (idempotencia del commit)."""
    with session_scope() as s:
        tx = s.get(WebpayTx, token)
        if tx is None:
            return
        tx.status = status
        tx.result = result
        if commit_response is not None:
            tx.commit_response = commit_response
        if reported:
            tx.reported_at = _utcnow()


def mark_reported(token: str) -> None:
    with session_scope() as s:
        tx = s.get(WebpayTx, token)
        if tx is not None:
            tx.reported_at = _utcnow()


def pending_older_than(minutes: int) -> list[WebpayTx]:
    """Tx aún INITIALIZED con más de `minutes` desde su creación (reconciliador)."""
    cutoff = _utcnow() - dt.timedelta(minutes=minutes)
    with session_scope() as s:
        rows = s.scalars(
            select(WebpayTx).where(
                WebpayTx.status == STATUS_INITIALIZED,
                WebpayTx.created_at < cutoff,
            )
        ).all()
        # Desligar de la sesión (expire_on_commit=False ya lo permite).
        return list(rows)


# ───────────────────────────── app_config ─────────────────────────────

def set_config(key: str, value: str) -> None:
    with session_scope() as s:
        row = s.get(AppConfig, key)
        if row is None:
            s.add(AppConfig(key=key, value=value))
        else:
            row.value = value


def get_config(key: str) -> str | None:
    with session_scope() as s:
        row = s.get(AppConfig, key)
        return row.value if row else None
