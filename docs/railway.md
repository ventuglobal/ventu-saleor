# Proyecto Railway `ventu-saleor`

Inventario del ambiente `production` tal como corre hoy (importado el 2026-09-26).
Proyecto `9d3ae1a2-0d29-4eac-9100-610905e51e41`, workspace "ventu's Projects",
región `sfo`, una réplica por servicio. Aquí van solo nombres de variables:
los valores viven en Railway (`railway variables --service <nombre>`).

## Servicios con código en este repo

Se despliegan solos al hacer push a `main` (repo `ventuglobal/ventu-saleor`).

| Servicio | Carpeta | Builder | Healthcheck | Dominio |
|---|---|---|---|---|
| `ventu` | `apps/ventu` | Railpack | — | ventu-production.up.railway.app |
| `ventu-b2b` | `apps/ventu-b2b` | Railpack | `/health` | ventu-b2b-production.up.railway.app |
| `ventu-pagos` | `apps/ventu-pagos` | Dockerfile | `/health` | ventu-pagos-production.up.railway.app |
| `storefront` | `storefront` | Railpack | — | storefront-production-4c25.up.railway.app (puerto 8080) |

Variables:

- **ventu**: `PRICING_CHANNELS`, `PRICING_IVA_RATE`, `PRICING_MARKUP`, `PRICING_ROUND_TO`,
  `SALEOR_API_URL`, `SALEOR_AUTH_TOKEN`, `SALEOR_CREATE_MISSING`, `SALEOR_ENSURE_PUBLISHED`,
  `SALEOR_WAREHOUSE_ID`, `SALEOR_WAREHOUSE_SLUG`, `VENTU_ADMIN_TOKEN`.
- **ventu-b2b**: `B2B_CANAL_CARRITO`, `B2B_DEFAULT_NIVEL_PRECIO`, `SALEOR_API_URL`,
  `SALEOR_AUTH_TOKEN`, `SALEOR_PRODUCTS_TOKEN`, `STOREFRONT_URL`.
- **ventu-pagos**: `PORT`, `SALEOR_API_URL`, `SALEOR_AUTH_TOKEN`, `SALEOR_WEBHOOK_SECRET`,
  `VENTU_PAGOS_RETURN_URL`, `WEBPAY_ENV`.
- **storefront**: `B2B_APP_URL`, `B2B_CHANNELS`, `NEXT_PUBLIC_DEFAULT_CHANNEL`,
  `NEXT_PUBLIC_DEFAULT_LOCALE`, `NEXT_PUBLIC_SALEOR_API_URL`, `NEXT_PUBLIC_STOREFRONT_LOCALES`,
  `NEXT_PUBLIC_STOREFRONT_URL`, `SALEOR_APP_TOKEN`, `STOREFRONT_CHANNELS`.

## Landings (subidas con `railway up`, sin repo conectado)

El código se recuperó de los contenedores en vivo y quedó en `landing/` y
`landing-global/`. Railway **no** las redespliega al hacer push: hay que subirlas a mano.

| Servicio | Carpeta | Dominios | API |
|---|---|---|---|
| `landing` | `landing/` | ventu.cl, www.ventu.cl | `POST /api/registro` (seller, supplier, carrier) |
| `landing-global` | `landing-global/` | ventuglobal.com, www.ventuglobal.com (puerto 8080) | `POST /api/contact` (investor, partner, talent) |

Ambas son Express + `pg`, sirven los estáticos de su carpeta y guardan los
formularios en la tabla `registrations` de la base que indique `DATABASE_URL`
(`landing-global` marca sus filas con `source = 'ventuglobal'`).

```bash
cd landing && railway up --service landing
cd landing-global && railway up --service landing-global
```

## Saleor (imágenes oficiales, sin código propio)

| Servicio | Imagen | Configuración relevante |
|---|---|---|
| `saleor-api` | `ghcr.io/saleor/saleor:3.23` | Puerto 8000. Pre-deploy: `migrate` y asegura el superusuario del dashboard. |
| `saleor-worker` | `ghcr.io/saleor/saleor:3.23` | Start: `celery -A saleor --app=saleor.celeryconf:app worker --loglevel=info` |
| `saleor-dashboard` | `ghcr.io/saleor/saleor-dashboard:3.23` | Puerto 80. Variable `API_URL`. |

Dominios: saleor-api-production-3f5f.up.railway.app y
saleor-dashboard-production-31d1.up.railway.app.

Variables de `saleor-api` (el worker usa las mismas salvo `ALLOWED_*` y `DJANGO_SUPERUSER_*`):
`ALLOWED_GRAPHQL_ORIGINS`, `ALLOWED_HOSTS`, `AWS_ACCESS_KEY_ID`, `AWS_MEDIA_BUCKET_NAME`,
`AWS_MEDIA_CUSTOM_DOMAIN`, `AWS_QUERYSTRING_AUTH`, `AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME`,
`AWS_SECRET_ACCESS_KEY`, `CACHE_URL`, `CELERY_BROKER_URL`, `DATABASE_URL`, `DEFAULT_CHANNEL_SLUG`,
`DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD`, `PUBLIC_URL`, `RSA_PRIVATE_KEY`, `SECRET_KEY`.

## Datos

| Servicio | Imagen | Volumen |
|---|---|---|
| `Postgres` | `postgres-ssl:15` | `postgres-volume` (50 GB) en `/var/lib/postgresql/data` |
| `Postgres--2ho` | `postgres-ssl:18` | `postgres-volume-kIYF` (50 GB) en `/var/lib/postgresql/data` |
| `Redis` | `redis:8.2.9` | `redis-volume` (50 GB) en `/data` |

## Trabajo abierto en GitHub

Las demás ramas `claude/*` ya están fusionadas en `main` (por squash).

| PR | Rama | Tema |
|---|---|---|
| #20 | `claude/saleor-development-status-ancnah` | Celery fuera de modo eager y memoria |
| #11 | `claude/pagos-subscriptions` | Subscriptions en webhooks y errores de Transbank |
| #4 | `claude/ventu-facturacion` | App Ventu Facturación SII |
