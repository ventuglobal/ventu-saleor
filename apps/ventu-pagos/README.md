# app Ventu Pagos

App de **pagos** (Webpay/Transbank) de Ventu 2.0 — su propia Saleor App por el
permiso especial `HANDLE_PAYMENTS` (Saleor la trata como payment gateway) y por
aislamiento de seguridad. Modo de integración: **Inyecta** (webhooks síncronos
de transacción, en el camino crítico del checkout, presupuesto < 10 s).

Paquete importable: `ventu_pagos/` (la carpeta de deploy usa guion).

## Flujo Webpay Plus

```
storefront → paymentGatewayInitialize (Saleor)
  → TRANSACTION_INITIALIZE_SESSION → webpay.create() → result CHARGE_ACTION_REQUIRED + url
  → cliente paga en Webpay → redirige (POST token_ws) a /webpay/return
  → webpay.commit(token) → AUTHORIZED/FAILED → transacción Saleor actualizada
  → (OMS) capture diferido cuando se confirma abastecimiento
  → refund / void según corresponda
```

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/health` | liveness + ambiente Webpay |
| GET | `/manifest` | manifest de payment app (`HANDLE_PAYMENTS`) |
| POST | `/register` | recibe el `auth_token` al instalar |
| POST | `/webhooks/saleor` | eventos síncronos de pago (initialize/charge/refund/…) |
| POST | `/webpay/return` | retorno de Webpay → `commit` |

## Config (env)

Por defecto usa el **ambiente de integración** con las credenciales públicas de
prueba de Transbank.

```
WEBPAY_ENV=integration            # integration | production
WEBPAY_COMMERCE_CODE=597055555532 # test
WEBPAY_API_KEY=...                # test (ver config.py)
VENTU_PAGOS_RETURN_URL=https://<host>/webpay/return
SALEOR_WEBHOOK_SECRET=...         # valida los webhooks entrantes
```

## Estado

- ✅ Estructura: manifest, dispatch de webhooks, cliente Webpay (create/commit/refund), `/webpay/return`, helpers puros testeados.
- ⏳ Pendiente (contra payload real + credenciales): mapeo fino de payloads de transacción, `transactionUpdate`/report a Saleor tras commit, capture diferido gobernado por OMS, y persistencia del token de la App.

> Local: `pip install -r requirements.txt && PYTHONPATH=. uvicorn ventu_pagos.main:app --port 8090`
