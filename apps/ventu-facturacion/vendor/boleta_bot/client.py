#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cliente HTTP firmado SigV4 contra la API Gateway de e-Boleta (auth AWS_IAM).

Usa botocore.auth.SigV4Auth (probado en producción) para firmar; el cuerpo
firmado son exactamente los bytes enviados.
"""
import json
import logging
from typing import Any, Optional

import requests
from botocore.auth import SigV4Auth

# botocore en DEBUG imprime el CanonicalRequest con el x-amz-security-token
# (credencial temporal). Lo silenciamos para no filtrarlo en logs (crítico en batch).
for _n in ("botocore", "botocore.auth", "botocore.credentials", "urllib3"):
    logging.getLogger(_n).setLevel(logging.WARNING)
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from . import config
from .auth import get_aws_credentials


def signed_request(method: str, url: str, body: Optional[dict] = None,
                   timeout: int = 90) -> requests.Response:
    """Firma SigV4 y ejecuta una request contra execute-api (us-east-1)."""
    creds = get_aws_credentials()
    bot_creds = Credentials(creds["access_key"], creds["secret_key"], token=creds["token"])

    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}

    aws_req = AWSRequest(method=method, url=url, data=data, headers=headers)
    SigV4Auth(bot_creds, config.SIGV4_SERVICE, config.AWS_REGION).add_auth(aws_req)
    prepared = aws_req.prepare()

    return requests.request(
        method, url, data=data, headers=dict(prepared.headers), timeout=timeout)


def get_emisor_info(rut_empresa: str = None, rut_usuario: str = None) -> Any:
    """GET info-emisor-usuario/{rutEmpresa}/{rutUsuario} → datos del emisor (Meta)."""
    rut_empresa = (rut_empresa or config.RUT_EMPRESA).strip()
    rut_usuario = (rut_usuario or config.SII_RUT_USUARIO).strip()
    # La API espera el RUT empresa SIN dv (solo número) según la captura.
    rut_emp_num = rut_empresa.split("-")[0].replace(".", "")
    url = f"{config.INFO_EMISOR_URL}/{rut_emp_num}/{rut_usuario}"
    resp = signed_request("GET", url)
    resp.raise_for_status()
    return resp.json()
