# app Ventu Pagos

App de **pagos** de Ventu 2.0 — su propia Saleor App por el permiso especial
`HANDLE_PAYMENTS` (Saleor la trata como payment gateway) y por aislamiento de
seguridad: el token de pagos no se mezcla con `MANAGE_ORDERS` / `MANAGE_PRODUCTS`.

Modo de integración: **Inyecta** (webhooks síncronos de transacción, en el
camino crítico del checkout, presupuesto < 10 s).

## Alcance (fase posterior)

Media entre Saleor y **Webpay / Transbank**:

- `PAYMENT_GATEWAY_INITIALIZE_SESSION` → crea la transacción y devuelve el redirect.
- `TRANSACTION_INITIALIZE` / `TRANSACTION_CHARGE_REQUESTED` → charge.
- `TRANSACTION_REFUND_REQUESTED`, `TRANSACTION_CANCELATION_REQUESTED`.
- `return_url` de Webpay → `commit` → marca la transacción como autorizada/capturada.

El **capture diferido** (cobrar cuando el abastecimiento se confirma) lo gobierna
el módulo **OMS** de la app Ventu, no el checkout: OMS decide el momento y
dispara el charge.

> Placeholder: sin código todavía. Se implementa después de que Catálogo,
> Pricing y Storefront estén vivos (paso 5 del roadmap).
