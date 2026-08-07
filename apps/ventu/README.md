# app Ventu

El **cerebro** de Ventu 2.0 sobre Saleor: la app principal que aloja los módulos
que extienden Saleor (Ley 4 de la constitución). Se registra como **una** Saleor
App con permisos `MANAGE_PRODUCTS` / `MANAGE_ORDERS` / `MANAGE_CHANNELS`. Pagos
va en una app aparte (`apps/ventu-pagos`) por su permiso especial.

## Módulos

| Módulo | Modo | Estado |
|---|---|---|
| `catalog/` — Catálogo & Abastecimiento | Publica | **listo** (crea/actualiza, stock, visibilidad) |
| `pricing/` — Pricing | Publica | **listo** (costo → margen/fees/IVA → channel-listing) |
| OMS & Facturación SII | Reacciona | stub (webhook de órdenes recibido, sin despachar) |
| Impuestos / Envíos | Inyecta | pendiente |

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/manifest` | manifest para instalar la App en Saleor |
| POST | `/register` | recibe el `auth_token` que emite Saleor al instalar |
| POST | `/webhooks/saleor` | eventos async de orden (→ OMS/Facturación, stub) |
| POST | `/catalog/publish` | publica un lote de variantes (crea/actualiza + stock) |
| POST | `/pricing/publish` | computa precio final por channel y lo escribe |
| POST | `/pricing/quote` | dry-run: devuelve el precio computado sin escribir |

## Catálogo — publicar

```bash
curl -X POST http://localhost:8080/catalog/publish \
  -H "Authorization: Bearer $VENTU_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"items":[{"sku":"UBNT-ROUTER-X","available":42,
                 "prices":[{"channel_slug":"retail-cl","amount":12990}]}]}'
```

El publicador resuelve la variante por SKU; si no existe (y `SALEOR_CREATE_MISSING`
está activo) **crea** un producto simple con su variante (ProductType por defecto
"Ventu Default"). Luego fija stock de forma absoluta e idempotente
(`quantity = available_deseado + allocated_actual` en el warehouse VENTU),
precio por channel, y asegura la publicación.

> Atributos ricos del catálogo normalizado (marca, categoría, imágenes) se
> agregan en un incremento posterior; hoy la creación usa un producto simple.

## Local

```bash
pip install -r requirements.txt
PYTHONPATH=.. uvicorn ventu.main:app --reload --port 8080   # desde apps/
```

## Config (env)

Ver `.env.example` en la raíz: `SALEOR_API_URL`, `SALEOR_AUTH_TOKEN`,
`SALEOR_WAREHOUSE_ID` / `SALEOR_WAREHOUSE_SLUG`, `SALEOR_ENSURE_PUBLISHED`,
`VENTU_ADMIN_TOKEN`, `SALEOR_WEBHOOK_SECRET`.
