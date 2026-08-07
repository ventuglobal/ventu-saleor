"""Módulo Pricing (App Ventu).

Dueño de las reglas de precio (margen, fees, IVA, redondeo). Computa el precio
final por channel a partir del costo y **publica** los channel-listings de Saleor
(Saleor no calcula precio: lo muestra). Modo de integración: Publica.

Constitución: las promociones/impuestos nativos de Saleor se gobiernan o
desactivan; el precio publicado ya trae todo incluido.
"""
