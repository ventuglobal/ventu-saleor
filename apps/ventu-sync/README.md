# ventu-sync

Ventu Sync App — el lado **entrante** de la sincronización (Saleor → Ventu).
Recibe los webhooks de Saleor y reenvía las órdenes al backend Ventu. La
sincronización **saliente** (Ventu → Saleor) vive en el backend Ventu
(`channel_sync`), no aquí.

## Local

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
# http://localhost:8080/health
# http://localhost:8080/manifest
```

## Registrar como Saleor App

En el Dashboard: **Extensiones → Add → Install from manifest** apuntando a
`https://<host>/manifest`. Saleor pedirá el `tokenTargetUrl` (`/register`, aún
por implementar) y creará la App con permisos `MANAGE_ORDERS` / `MANAGE_PRODUCTS`.
El token resultante es el que usa el backend Ventu (`SALEOR_AUTH_TOKEN`) para la
sincronización saliente.

## Pendiente (skeleton)

- `POST /register`: recibir y persistir el `auth_token` que emite Saleor al
  instalar la App.
- Validación HMAC del webhook con `SALEOR_WEBHOOK_SECRET` (ya cableada; falta
  confirmar el header exacto que envía tu versión de Saleor).
- Mapeo del payload de orden de Saleor → esquema del endpoint de Ventu
  (`/integrations/saleor/orders/`), con idempotencia por id de orden.
