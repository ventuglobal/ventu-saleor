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
| `worker` | Celery: tareas asíncronas de Saleor (descarga de imágenes, webhooks, reindexado) | Misma imagen que `api`, otro comando |
| `dashboard` | Saleor Dashboard | Imagen oficial `ghcr.io/saleor/saleor-dashboard` (pin) |
| `ventu` | **App Ventu**: catálogo + pricing, y recibe los webhooks de orden | Código propio (`apps/ventu/`) |
| `ventu-pagos` | **App Pagos**: Webpay/Transbank (`HANDLE_PAYMENTS`) | Código propio (`apps/ventu-pagos/`) |
| `ventu-b2b` | **App B2B**: empresa por RUT, carrito de cotización, crédito | Código propio (`apps/ventu-b2b/`) |
| `storefront` | Tienda pública (Next.js) | `git subtree` del oficial `saleor/storefront` (remote `upstream`) |
| `db`, `redis` | Postgres + Redis | Imágenes oficiales |

`worker` no es opcional: ver § **Memoria y dimensionamiento**.

## Flujo de sincronización (bidireccional)

- **Ventu → Saleor** (saliente): stock/catálogo/precio. Vive en el backend
  Ventu (`channel_sync` + `propagators/saleor.py`). Empuja por GraphQL usando el
  token de la Saleor App. Modelo de stock:
  `quantity = available_deseado + allocated_actual` sobre el warehouse global
  "VENTU".
- **Saleor → Ventu** (entrante): órdenes/eventos. Los recibe la app `ventu` vía
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
- **ventu / ventu-pagos / ventu-b2b** → código propio, sin upstream.

**Automático:** `renovate.json` hace que Renovate vigile los releases de Saleor
y abra un PR cuando salga una versión nueva de las imágenes. Railway levanta el
PR environment para probarlo; si está OK, se mergea. Ese es el "siempre
sincronizado" sin trabajo manual.

## Desarrollo local

```bash
cp .env.example .env       # completar secretos
docker compose up -d db redis
docker compose up api worker dashboard ventu
# api:       http://localhost:8000/graphql/
# dashboard: http://localhost:9000/
# ventu:     http://localhost:8080/health
```

Primer arranque de Saleor (migraciones + superuser + poblar):
```bash
docker compose run --rm api python manage.py migrate
docker compose run --rm api python manage.py createsuperuser
docker compose run --rm api python manage.py populatedb   # datos demo (opcional)
```

Provisionamiento del canal (ver plan): crear el warehouse global **VENTU**,
los channels (`retail-cl`, `b2b-cl`), y registrar la Saleor App apuntando a
la app `ventu`. Luego, en el backend Ventu:
```bash
python manage.py set_saleor_channel --channel-slug retail-cl
```

## Despliegue en Railway

Un servicio de Railway por componente, todos en el mismo proyecto:

1. Conecta este repo a un proyecto de Railway.
2. Crea servicios: **api**, **worker** y **dashboard** (desde imagen Docker, pin
   del tag), **ventu**, **ventu-pagos**, **ventu-b2b**, **storefront**, más
   **Postgres** y **Redis** (plugins de Railway).
3. Variables: usa `.env.example` como referencia. `DATABASE_URL` y `REDIS_URL`
   los inyecta Railway desde los plugins; **`CELERY_BROKER_URL` hay que
   definirla a mano** (Railway no la inyecta, y sin ella el stack funciona pero
   consume varias veces más memoria — ver abajo).
4. `api` y `worker` necesitan **start command propio** en Railway; el CMD de la
   imagen no sirve tal cual (§ Memoria). Copiá los de `docker-compose.yml`.
5. Activa **auto-deploy** en la rama de producción y **PR environments** para
   ambientes efímeros por pull request. Cada PR environment levanta el stack
   completo y se factura mientras el PR siga abierto: activá *sleep* para los
   ambientes efímeros y cerrá los PR que ya no avanzan.

## Memoria y dimensionamiento

Railway factura memoria (~US$10/GB-mes), así que el dimensionamiento es costo
directo. Tres cosas de la configuración por defecto la disparan:

**1. Los workers de gunicorn nunca reciclan.** El CMD de la imagen 3.20 es
`gunicorn --workers 4` sin `--max-requests`: el pico de memoria de cualquier
request se vuelve el piso permanente del proceso. Medido sobre esa imagen, con
el CMD original:

| | Memoria del contenedor `api` |
|---|---|
| Arranque, 4 workers cargados | 359 MB |
| Tras ~36 introspecciones GraphQL | 523 MB |
| En reposo, 10 min después | **520 MB** — no baja |

Con el `command` de `docker-compose.yml` (2 workers, `--max-requests 1000
--max-requests-jitter 100`), el mismo ejercicio: arranca en 286 MB, sube a
428 MB, y al cruzar los 1000 requests por worker **vuelve a 306 MB** y se queda
ahí. Eso es el reciclado devolviendo la memoria al sistema.

> Saleor ya arregló esto aguas arriba: su imagen actual arranca con
> `uvicorn --workers=2 --limit-max-requests=10000`. El tag 3.20 (LTS) es
> anterior a ese cambio, así que hay que suplirlo desde acá.

**2. Calentar miniaturas que nadie pide.** Saleor genera cada miniatura
**dentro del request web** (`saleor/thumbnail/views.py` llama a
`create_thumbnail()` en línea, no por Celery), así que cada variante calentada
es un decode+resize de Pillow en un worker de `api`. Por eso importa calentar
solo lo que se usa: los defaults de `THUMBNAIL_WARM_*` salen de las queries
reales del storefront (1024 y 2048, ambas WEBP) en vez de una escalera
genérica. Ver `apps/ventu/config.py`.

**3. Celery en modo *eager*.** Saleor lee `CELERY_BROKER_URL` para el broker —
**no** `REDIS_URL`, que solo alimenta el caché de Django. Sin esa variable,
`app.conf.task_always_eager` queda en `True` y las tareas asíncronas corren
dentro del worker web: descarga de imágenes de producto, entrega de webhooks y
reindexado de búsqueda. (Las miniaturas **no** — ver punto 2.) El servicio
`worker` existe para eso.

> Es un intercambio, no una rebaja: el `worker` agrega ~565 MB propios. Lo que
> compra es que el trabajo pesado deje de ocurrir en el camino del request y
> pase a un servicio que se puede dimensionar, reciclar y dormir aparte.

Al cambiar cualquiera de los tres, medí antes y después:

```bash
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}'
```

Con eso el flujo es: pedir tarea desde el móvil → PR → ambiente de preview en
Railway → merge → producción, sin depender de ninguna máquina local.

## Estado

- [x] Sincronización saliente Ventu → Saleor (en el backend Ventu, PR #19 de ese repo).
- [x] `docker-compose` + servicios base.
- [x] App Ventu (`apps/ventu/`): catálogo, pricing y webhooks de orden.
- [x] Storefront oficial de Saleor vendido por subtree en `./storefront` + servicio en compose (`make storefront-pull` para actualizar), en es-CL.
- [x] Payment App Webpay/Transbank (`apps/ventu-pagos/`).
- [x] App B2B 1.0 (`apps/ventu-b2b/`): empresa por RUT, carrito de cotización, crédito.
- [ ] App Facturación SII (DTE) — requisito legal para vender a empresas.
- [ ] Integración Maxxa para la evaluación de crédito B2B.
