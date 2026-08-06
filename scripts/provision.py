#!/usr/bin/env python3
"""Provisiona lo mínimo del plan en un Saleor recién levantado:

  1. Warehouse global "VENTU".
  2. Channels de venta (por defecto: retail-cl, b2b-cl) en CLP.

Al final imprime los `gid` que el **backend Ventu** necesita en su .env:

    SALEOR_WAREHOUSE_ID=<gid del warehouse VENTU>

Idempotente: si algo ya existe, Saleor devuelve un error de "ya existe" que el
script reporta y sigue (no aborta).

Uso:
    SALEOR_API_URL=http://localhost:8000/graphql/ \\
    SALEOR_AUTH_TOKEN=<token de staff/app con MANAGE_*> \\
    python scripts/provision.py --channels retail-cl,b2b-cl

Sin dependencias externas (usa urllib de la stdlib).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

API_URL = os.getenv("SALEOR_API_URL", "http://localhost:8000/graphql/")
AUTH_TOKEN = os.getenv("SALEOR_AUTH_TOKEN", "")

WAREHOUSE_SLUG = "ventu"
WAREHOUSE_NAME = "VENTU"

_CREATE_WAREHOUSE = """
mutation($input: WarehouseCreateInput!) {
  createWarehouse(input: $input) {
    warehouse { id slug }
    errors { field message code }
  }
}
"""

_CREATE_CHANNEL = """
mutation($input: ChannelCreateInput!) {
  channelCreate(input: $input) {
    channel { id slug currencyCode }
    errors { field message code }
  }
}
"""

_WAREHOUSE_BY_SLUG = """
query($slug: String!) {
  warehouses(first: 1, filter: {slugs: [$slug]}) { edges { node { id slug } } }
}
"""


def gql(query: str, variables: dict) -> dict:
    if not AUTH_TOKEN:
        sys.exit("ERROR: SALEOR_AUTH_TOKEN no seteado.")
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API_URL, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _errors(node: dict, key: str) -> list:
    return ((node.get("data") or {}).get(key) or {}).get("errors") or []


def ensure_warehouse() -> str | None:
    # ¿ya existe?
    existing = gql(_WAREHOUSE_BY_SLUG, {"slug": WAREHOUSE_SLUG})
    edges = (((existing.get("data") or {}).get("warehouses") or {}).get("edges")) or []
    if edges:
        wid = edges[0]["node"]["id"]
        print(f"• Warehouse '{WAREHOUSE_NAME}' ya existe → {wid}")
        return wid

    resp = gql(_CREATE_WAREHOUSE, {"input": {
        "name": WAREHOUSE_NAME,
        "slug": WAREHOUSE_SLUG,
        "address": {"streetAddress1": "N/A", "city": "Santiago",
                    "country": "CL", "postalCode": "0000000"},
    }})
    errs = _errors(resp, "createWarehouse")
    if errs:
        print(f"! Warehouse: {errs}")
        return None
    wid = (((resp.get("data") or {}).get("createWarehouse") or {}).get("warehouse") or {}).get("id")
    print(f"✓ Warehouse '{WAREHOUSE_NAME}' creado → {wid}")
    return wid


def ensure_channel(slug: str) -> None:
    name = slug.replace("-", " ").title()
    resp = gql(_CREATE_CHANNEL, {"input": {
        "name": name, "slug": slug,
        "currencyCode": "CLP", "defaultCountry": "CL",
    }})
    errs = _errors(resp, "channelCreate")
    if errs:
        # típicamente "ya existe" → informativo, no fatal
        print(f"• Channel '{slug}': {errs}")
        return
    node = (((resp.get("data") or {}).get("channelCreate") or {}).get("channel") or {})
    print(f"✓ Channel '{slug}' creado → {node.get('id')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channels", default="retail-cl,b2b-cl",
                    help="Lista separada por comas de slugs de channel.")
    args = ap.parse_args()

    print(f"Saleor API: {API_URL}\n")
    wid = ensure_warehouse()
    for slug in [c.strip() for c in args.channels.split(",") if c.strip()]:
        ensure_channel(slug)

    print("\n── Config para el backend Ventu (.env) ──")
    if wid:
        print(f"SALEOR_WAREHOUSE_ID={wid}")
    print("SALEOR_WAREHOUSE_SLUG=ventu")
    print("\nRecordá: vincular el warehouse a las shipping zones y registrar la")
    print("Ventu Sync App (apps/ventu-sync) para obtener el SALEOR_AUTH_TOKEN.")


if __name__ == "__main__":
    main()
