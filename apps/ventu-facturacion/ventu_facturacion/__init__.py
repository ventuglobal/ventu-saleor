"""Paquete `ventu_facturacion` — app de Facturación SII de Ventu 2.0.

Reacciona a ORDER_FULLY_PAID de Saleor y emite el DTE (boleta 39 / factura 33)
vía los paquetes portados de Ventu 1.0 (`facturador_v2`, `boleta_bot`,
vendorizados en ../vendor). El folio se estampa en `order.metadata`.
"""
