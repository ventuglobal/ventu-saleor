"""Modelos de persistencia de Ventu Pagos.

`webpay_tx`  — una fila por transacción Webpay (idempotencia, verificación de
               monto, insumo del reconciliador).
`app_config` — clave/valor para el `auth_token` de la App y la URL de Saleor.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, BigInteger, DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


# Estados internos de una transacción Webpay.
STATUS_INITIALIZED = "INITIALIZED"
STATUS_AUTHORIZED = "AUTHORIZED"
STATUS_FAILED = "FAILED"
STATUS_REFUNDED = "REFUNDED"
STATUS_ABORTED = "ABORTED"  # el cliente anuló en el formulario de Webpay


class WebpayTx(Base):
    __tablename__ = "webpay_tx"

    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    buy_order: Mapped[str] = mapped_column(String(32), index=True)
    session_id: Mapped[str] = mapped_column(String(64))
    saleor_transaction_id: Mapped[str | None] = mapped_column(String(128), index=True, default=None)
    checkout_id: Mapped[str | None] = mapped_column(String(128), default=None)
    channel_slug: Mapped[str | None] = mapped_column(String(128), default=None)
    amount: Mapped[int] = mapped_column(BigInteger)  # CLP entero
    status: Mapped[str] = mapped_column(String(32), default=STATUS_INITIALIZED, index=True)
    # Resultado de Webpay que mapeamos a Saleor (CHARGE_SUCCESS/FAILURE) una vez cerrado.
    result: Mapped[str | None] = mapped_column(String(32), default=None)
    commit_response: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    reported_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    @property
    def is_closed(self) -> bool:
        """True si la tx ya tiene un resultado final (no reprocesar commit)."""
        return self.result is not None


class AppConfig(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
