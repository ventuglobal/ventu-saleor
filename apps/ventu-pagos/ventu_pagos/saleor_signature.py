"""Verificación de la firma de los webhooks de Saleor.

Saleor firma los webhooks con **JWS RS256 de payload detached** en el header
`Saleor-Signature` (`<header>..<signature>`), verificable contra las llaves
públicas de `{SALEOR_API_URL}/.well-known/jwks.json`. El método HMAC con
`secretKey` es legacy/deprecado y solo se usa como respaldo si está configurado.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

import httpx
from jwcrypto import jwk, jws

from . import config, store

logger = logging.getLogger("ventu.pagos.signature")

_JWKS_TTL = 600  # s
_jwks_cache: dict[str, object] = {"keyset": None, "fetched_at": 0.0}


def _saleor_api_url() -> str:
    # Preferir el valor persistido al instalar; si no, el de env.
    return (store.get_config("saleor_api_url") or config.SALEOR_API_URL or "").rstrip("/")


def _jwks_url() -> str:
    base = _saleor_api_url()
    if not base:
        return ""
    # SALEOR_API_URL suele terminar en /graphql/; el JWKS cuelga del dominio.
    origin = base
    for suffix in ("/graphql/", "/graphql"):
        if origin.endswith(suffix):
            origin = origin[: -len(suffix)]
            break
    return f"{origin}/.well-known/jwks.json"


def _load_jwks(*, force: bool = False) -> jwk.JWKSet | None:
    now = time.time()
    if (
        not force
        and _jwks_cache["keyset"] is not None
        and now - float(_jwks_cache["fetched_at"]) < _JWKS_TTL
    ):
        return _jwks_cache["keyset"]  # type: ignore[return-value]
    url = _jwks_url()
    if not url:
        return None
    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        keyset = jwk.JWKSet.from_json(resp.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("no se pudo obtener JWKS de %s: %s", url, exc)
        return None
    _jwks_cache["keyset"] = keyset
    _jwks_cache["fetched_at"] = now
    return keyset


def _verify_jws(raw: bytes, signature: str) -> bool:
    token = signature.strip()
    sig = jws.JWS()
    try:
        sig.deserialize(token)
    except Exception as exc:  # noqa: BLE001
        logger.warning("firma JWS malformada: %s", exc)
        return False

    kid = None
    try:
        kid = (sig.jose_header or {}).get("kid")
    except Exception:  # noqa: BLE001
        kid = None

    for force in (False, True):  # reintenta con JWKS fresco ante kid desconocido
        keyset = _load_jwks(force=force)
        if keyset is None:
            return False
        key = keyset.get_key(kid) if kid else None
        candidates = [key] if key is not None else list(keyset)
        for candidate in candidates:
            try:
                sig.verify(candidate, detached_payload=raw)
                return True
            except Exception:  # noqa: BLE001
                continue
        if key is not None:  # el kid existía pero no validó; no insistas
            break
    return False


def _verify_hmac(raw: bytes, signature: str) -> bool:
    expected = hmac.new(
        config.SALEOR_WEBHOOK_SECRET.encode(), raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify(raw: bytes, signature: str | None) -> bool:
    """True si la firma del webhook es válida (o si la verificación está apagada)."""
    if not config.VERIFY_SIGNATURE:
        return True
    if not signature:
        return False
    # Camino principal: JWS detached contra JWKS.
    if _verify_jws(raw, signature):
        return True
    # Respaldo legacy: HMAC con secretKey (si el webhook se configuró así).
    if config.SALEOR_WEBHOOK_SECRET and _verify_hmac(raw, signature):
        return True
    return False
