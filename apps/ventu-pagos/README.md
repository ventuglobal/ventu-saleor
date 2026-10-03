# app Ventu Pagos

App de **pagos** (Webpay/Transbank) de Ventu 2.0 — su propia Saleor App por el
permiso especial `HANDLE_PAYMENTS` (Saleor la trata como payment gateway) y por
aislamiento de seguridad. Modo de integración: **Inyecta** (webhooks síncronos
de transacción, en el camino crítico del checkout, presupuesto < 10 s).

Paquete importable: `ventu_pagos/` (la carpeta de deploy usa guion).

Webpay Plus corre **solo en el canal `retail-cl`** (ver `WEBPAY_CHANNELS`); B2B
(Transferencia/Maxxa) no pasa por esta app.

## Regla de oro

Un pago está aprobado **solo si el `commit` hecho por nuestro servidor devuelve
`response_code = 0` y `status = AUTHORIZED`**. Nada que llegue por el navegador
se da por bueno sin confirmar contra Transbank.

## Flujo Webpay Plus (captura simultánea)

```
storefront (retail-cl) → TRANSACTION_INITIALIZE_SESSION
  → valida canal + moneda CLP → webpay.create() → persiste webpay_tx (INITIALIZED)
  → result CHARGE_ACTION_REQUIRED + { data:{ webpayUrl, token } }
  → cliente paga en Webpay → return_url (storefront) → transactionProcess
  → TRANSACTION_PROCESS_SESSION → webpay.commit(token_ws)
      · verifica amount y buy_order contra lo guardado (si no cuadran → refund total)
      · AUTHORIZED + response_code 0 ⇒ CHARGE_SUCCESS (síncrono), si no CHARGE_FAILURE
  → metadata (authorization_code, payment_type_code, card_last4) best-effort
  → refund / cancelation según corresponda
```

`/webpay/return` queda como **fallback/testing** (commit idempotente directo); el
`return_url` del flujo normal apunta al storefront. El **reconciliador**
(`/tasks/reconcile`, cron) cierra transacciones INITIALIZED huérfanas (navegador
cerrado) consultando `status` en Webpay y reportando a Saleor vía
`transactionEventReport`.

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/health` | liveness + ambiente Webpay |
| GET | `/manifest` | manifest de payment app (`HANDLE_PAYMENTS` + subscription) |
| POST | `/register` | persiste el `auth_token` + `saleor_api_url` al instalar |
| POST | `/webhooks/saleor` | eventos síncronos de pago (verifica firma JWS) |
| GET/POST | `/webpay/return` | retorno de Webpay (fallback/testing) → `commit` |
| POST | `/tasks/reconcile` | reconciliador (protegido por `RECONCILE_TOKEN`) |

## Persistencia

SQLAlchemy sobre **Postgres** (`DATABASE_URL` en Railway) con **fallback SQLite**
local/tests. Tablas: `webpay_tx` (una fila por token, con `commit_response` crudo
y estado) y `app_config` (clave/valor: `auth_token`, `saleor_api_url`).

## Config (env)

Por defecto usa el **ambiente de integración** con las credenciales públicas de
prueba de Transbank.

```
WEBPAY_ENV=integration            # integration | production
WEBPAY_COMMERCE_CODE=597055555532 # test
WEBPAY_API_KEY=...                # test (ver config.py)
WEBPAY_CHANNELS=retail-cl         # canales habilitados (coma-separado)
WEBPAY_CURRENCY=CLP
DATABASE_URL=postgresql+psycopg://…   # fallback sqlite:///./ventu_pagos.db
SALEOR_API_URL=https://<saleor>/graphql/
STOREFRONT_URL=https://<storefront>
VENTU_PAGOS_RETURN_URL=https://<storefront>/checkout/webpay/retorno
VENTU_PAGOS_VERIFY_SIGNATURE=1    # 0 en local (sin firma)
RECONCILE_TOKEN=...               # Bearer de /tasks/reconcile
RECONCILE_AFTER_MIN=15
```

La firma de webhooks se verifica como **JWS RS256 detached** (`Saleor-Signature`)
contra `{SALEOR_API_URL}/.well-known/jwks.json`; HMAC (`SALEOR_WEBHOOK_SECRET`)
queda como fallback legacy.

## Estado

- ✅ Backend (Fases 1–2): persistencia, firma JWS, cliente Webpay con manejo de
  errores, commit idempotente con regla de oro + verificación monto/buy_order,
  aislamiento de canal, reconciliador, reporte `transactionEventReport`. 20 tests.
- ⏳ Pendiente (fuera de este código): contrato Transbank, validación formal con
  Transbank y producción (Fases 0/4/5/6).

## Desarrollo

```
cd apps/ventu-pagos
pip install -r requirements.txt pytest
pytest tests -q
PYTHONPATH=. VENTU_PAGOS_VERIFY_SIGNATURE=0 uvicorn ventu_pagos.main:app --port 8090
```
