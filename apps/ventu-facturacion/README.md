# app Ventu Facturación (SII)

Emite **boletas (DTE 39)** y **facturas (DTE 33)** al pagarse una orden. Es su
propia Saleor App (`MANAGE_ORDERS`) porque necesita **Playwright** para el login
del SII (el portal MiPyme bloquea el login headless) — un perfil de runtime
distinto al del "cerebro", por eso se aísla (constitución: extraer por driver real).

Modo de integración: **Reacciona** (async, `ORDER_FULLY_PAID`).

## Flujo

```
ORDER_FULLY_PAID → extrae receptor de order.metadata
  → RUT válido + razón social ? factura (DTE 33) : boleta (DTE 39)
  → emite (facturador_v2 / boleta_bot, vendorizados de 1.0)
  → estampa folio en order.metadata (ventu.dte.folio)
```

## Emisor (portado de Ventu 1.0)

`vendor/facturador_v2/` (factura: SII portal, Playwright login + firma
centralizada) y `vendor/boleta_bot/` (boleta: API firmada con AWS SigV4). Se
importan de forma **lazy** en `emitter.py`, así los tests de lógica pura no
requieren esas deps. Las credenciales SII/AWS las leen esos paquetes desde env.

## Robustez (100% automático)

- **Idempotencia**: si la orden ya tiene `ventu.dte.folio`, no re-emite.
- **Dead-letter**: si el emisor falla, marca `ventu.dte.status=error` en la
  orden y responde 200 (sin loop de reintentos); un reproceso/alerta lo recupera.

## Requisito del checkout

El storefront/checkout debe capturar los campos fiscales y estamparlos en la
orden como metadata: `ventu.rut`, `ventu.razon_social`, `ventu.giro`,
`ventu.direccion`, `ventu.comuna`, `ventu.ciudad`.

## Pendiente (contra SII/API reales)

Afinar el mapeo de líneas contra un payload real, `transactionUpdate`/reporte,
persistencia del token de la App, y el manejo de nota de crédito (anulación)
que ya expone `facturador_v2.emitir_nota_credito`.

> Tests: `pytest apps/ventu-facturacion/tests` (solo lógica pura, sin Playwright).
