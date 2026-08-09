# ventu-saleor

Stack de **Saleor** de Ventu: reemplazo de Shopify, operado como un canal de
venta de Ventu. Desplegable en **Railway** (auto-deploy + PR environments).

Ventu (backend Django) es la **fuente de verdad** de catálogo, stock y precios.
Este repo aloja la plataforma de venta; la sincronización saliente
(catálogo/stock/precio → Saleor) vive en el backend Ventu (app `channel_sync`).

## Componentes

| Servicio | Qué es | Origen |
|---|---|---|
| `api` | Saleor core (GraphQL API) | Imagen oficial `ghcr.io/saleor/saleor` (pin por versión) |
| `dashboard` | Saleor Dashboard | Imagen oficial `ghcr.io/saleor/saleor-dashboard` (pin) |
| `ventu-sync` | **Ventu Sync App**: recibe webhooks de Saleor (órdenes → Ventu) y aloja el token de la Saleor App | Código propio (`apps/ventu-sync/`) |
| `storefront` | Tienda pública (Next.js) | `git subtree` del oficial `saleor/storefront` (remote `upstream`) |
| `db`, `redis` | Postgres + Redis | Imágenes oficiales |

Webpay/Transbank (Payment App) se agrega en una fase posterior.

## Flujo de sincronización (bidireccional)

- **Ventu → Saleor** (saliente): stock/catálogo/precio. Vive en el backend
  Ventu (`channel_sync` + `propagators/saleor.py`). Empuja por GraphQL usando el
  token de la Saleor App. Modelo de stock:
  `quantity = available_deseado + allocated_actual` sobre el warehouse global
  "VENTU".
- **Saleor → Ventu** (entrante): órdenes/eventos. Los recibe `ventu-sync` vía
  webhooks de Saleor (`ORDER_CREATED`, `ORDER_FULLY_PAID`) y los reenvía al
  backend Ventu.

## Cómo se mantiene sincronizado con el Saleor oficial

No se forkea el código de Saleor (evita conflictos eternos). Cada componente:

- **api / dashboard** → imágenes Docker oficiales **fijadas por tag**.
  Actualizar = subir el tag. Sin merge, sin conflictos.
- **storefront** → `git subtree` del repo oficial con remote `upstream`:
  ```bash
  git remote add upstream https://github.com/saleor/storefront.git
  git subtree add  --prefix=storefront upstream main --squash   # una vez
  git subtree pull --prefix=storefront upstream main --squash   # traer updates
  ```
- **ventu-sync** → código propio, sin upstream.

**Automático:** `renovate.json` hace que Renovate vigile los releases de Saleor
y abra un PR cuando salga una versión nueva de las imágenes. Railway levanta el
PR environment para probarlo; si está OK, se mergea. Ese es el "siempre
sincronizado" sin trabajo manual.

## Desarrollo local

```bash
cp .env.example .env       # completar secretos
docker compose up -d db redis
docker compose up api dashboard ventu-sync
# api:       http://localhost:8000/graphql/
# dashboard: http://localhost:9000/
# ventu-sync http://localhost:8080/health
```

Primer arranque de Saleor (migraciones + superuser + poblar):
```bash
docker compose run --rm api python manage.py migrate
docker compose run --rm api python manage.py createsuperuser
docker compose run --rm api python manage.py populatedb   # datos demo (opcional)
```

Provisionamiento del canal (ver plan): crear el warehouse global **VENTU**,
los channels (`retail-cl`, `b2b-cl`), y registrar la Saleor App apuntando a
`ventu-sync`. Luego, en el backend Ventu:
```bash
python manage.py set_saleor_channel --channel-slug retail-cl
```

## Despliegue en Railway

Un servicio de Railway por componente, todos en el mismo proyecto:

1. Conecta este repo a un proyecto de Railway.
2. Crea servicios: **api** y **dashboard** (desde imagen Docker, pin del tag),
   **ventu-sync** (build desde `apps/ventu-sync/`), **storefront**, más
   **Postgres** y **Redis** (plugins de Railway).
3. Variables: usa `.env.example` como referencia. `DATABASE_URL` y `REDIS_URL`
   los inyecta Railway desde los plugins.
4. Activa **auto-deploy** en la rama de producción y **PR environments** para
   ambientes efímeros por pull request.

Con eso el flujo es: pedir tarea desde el móvil → PR → ambiente de preview en
Railway → merge → producción, sin depender de ninguna máquina local.

## Estado

- [x] Sincronización saliente Ventu → Saleor (en el backend Ventu, PR #19).
- [ ] `docker-compose` + servicios base (este scaffold).
- [ ] Ventu Sync App: webhooks de órdenes → Ventu (skeleton en `apps/ventu-sync/`).
- [x] Storefront oficial de Saleor vendido por subtree en `./storefront` + servicio en compose (`make storefront-pull` para actualizar).
- [ ] Payment App Webpay (fase posterior).
