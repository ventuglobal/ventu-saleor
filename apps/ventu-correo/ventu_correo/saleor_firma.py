"""Verificación de la firma de los webhooks de Saleor.

Saleor firma cada webhook de app con RS256 en un JWS de payload separado
(`Saleor-Signature: <cabecera>..<firma>`, con `b64: false`), usando la clave
que publica en /.well-known/jwks.json. Las claves se toman solo de la
instancia configurada en SALEOR_API_URL: un webhook de otra instancia de
Saleor no verifica aunque traiga una firma válida para la suya.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable, Dict, Optional

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from . import config

logger = logging.getLogger("ventu.correo")

# Tras una clave desconocida no se vuelve a pedir el JWKS antes de esto: una
# ráfaga de firmas falsas no debe convertirse en una ráfaga contra Saleor.
_REFRESCO_MIN_S = 60.0


class ClavesSaleor:
    def __init__(self, obtener: Optional[Callable[[], dict]] = None):
        self._obtener = obtener or self._descargar
        self._claves: Dict[str, object] = {}
        self._ultima = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _descargar() -> dict:
        url = config.jwks_url()
        if not url:
            raise RuntimeError("SALEOR_API_URL vacío")
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _refrescar(self, forzar: bool) -> None:
        with self._lock:
            ahora = time.monotonic()
            if self._claves and not forzar:
                return
            if self._claves and ahora - self._ultima < _REFRESCO_MIN_S:
                return
            jwks = self._obtener()
            claves = {}
            for k in jwks.get("keys", []):
                if k.get("kty") == "RSA":
                    claves[k.get("kid", "")] = RSAAlgorithm.from_jwk(json.dumps(k))
            self._claves = claves
            self._ultima = ahora

    def clave(self, kid: str):
        self._refrescar(forzar=False)
        if kid not in self._claves:
            # Saleor rotó la clave: se pide de nuevo, con freno.
            self._refrescar(forzar=True)
        return self._claves.get(kid)


claves = ClavesSaleor()


def verificar(cuerpo: bytes, firma: Optional[str],
              almacen: Optional[ClavesSaleor] = None) -> bool:
    """True si `firma` es una firma válida de Saleor sobre `cuerpo`."""
    almacen = almacen or claves
    if not firma:
        return False
    try:
        cabecera = jwt.get_unverified_header(firma)
        if cabecera.get("alg") != "RS256":
            return False
        clave = almacen.clave(cabecera.get("kid", ""))
        if clave is None:
            return False
        jwt.api_jws.decode_complete(firma, key=clave, algorithms=["RS256"],
                                    detached_payload=cuerpo)
        return True
    except jwt.PyJWTError as exc:
        logger.warning("(correo) firma de Saleor inválida: %s", exc)
        return False
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        # Sin poder bajar las claves no se puede verificar: se rechaza y Saleor
        # reintenta más tarde.
        logger.error("(correo) no se pudieron obtener las claves de Saleor: %s", exc)
        return False
