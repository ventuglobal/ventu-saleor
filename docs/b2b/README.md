# Ventu 2.0 — App B2B

Especificación de la App B2B y registro de funcionalidades futuras.

| Versión | Estado | Contenido |
|---|---|---|
| **B2B 1.0** | Especificada | MVP: identificar empresa, cotizar, solicitar crédito, comprar |
| **B2B 1.1+** | Registro | Backlog de funcionalidades futuras (§ Roadmap) |

Para abrir la compra en producción: **[lista de verificación de
lanzamiento](lanzamiento.md)** (tokens, Saleor, IVA, correo, aprobación de
empresas y prueba de humo).

---

# B2B 1.0 — MVP

## Objetivo

Permitir que una pyme se identifique como empresa dentro de Ventu, cotice,
compre sobre la infraestructura Saleor existente y pueda solicitar condiciones
de crédito.

No es una plataforma de *procurement* corporativo. El cliente objetivo no
requiere estructuras de usuarios, departamentos, centros de costo ni
aprobaciones internas.

## Principio de alcance

> Nada entra al 1.0 salvo que sea necesario para **registrar una empresa**,
> **cotizar**, **otorgar crédito** o **concretar una compra**.

La oportunidad comercial está en mantener el flujo corto: una pyme debería
pasar de conocer Ventu a comprar casi de inmediato.

## Responsabilidades

La App B2B hace cuatro cosas y ninguna más:

1. **Identificar** una empresa por su RUT
2. **Asociarla** al usuario y a sus órdenes
3. **Canalizar** su solicitud de crédito
4. **Convertir** una conversación de WhatsApp en un carrito recuperable

> **WhatsApp inicia la relación. El carrito mantiene la intención. Ventu cierra
> la transacción.**

Lo demás permanece donde está: Saleor administra productos, checkout y órdenes;
Pricing calcula precios; Facturación emite documentos tributarios.

**La App B2B no es un sistema financiero.** Registra la condición comercial
resultante o una referencia al sistema que la administra.

## Modelo de datos

### Company

Reside en `privateMetadata` del usuario de Saleor. En 1.0 la relación es
**1 usuario = 1 empresa**, lo que permite prescindir de base de datos propia
—coherente con las apps actuales de Ventu, que son sin estado.

```
rut                normalizado y validado (módulo 11)
razon_social
giro
contacto           email, teléfono
nivel_precio       canal en que compra la empresa
condicion_pago     contado | credito_30
credito_estado     sin_solicitud | pendiente | aprobada | rechazada
maxxa_ref          referencia a la solicitud/línea en Maxxa
estado             pendiente | aprobada — espejo en metadata pública (§ Registro)
alta               fecha del alta de la empresa (UTC)
```

**La identidad manda desde la privada.** RUT, razón social, giro y teléfono
van en `privateMetadata` y se copian a la `metadata` pública solo porque es lo
único que Saleor deja filtrar (buscar por RUT, listar pendientes). Saleor deja
que el cliente escriba la metadata pública de su propio usuario, así que esa
copia es un índice y nada que decida —facturar, detectar un RUT ya registrado,
aprobar— se lee de ahí: la búsqueda por RUT confirma cada coincidencia contra
el RUT privado. Las empresas anteriores a esta copia se siguen leyendo desde la
pública hasta que cualquier `PATCH` del staff congela su identidad en la
privada (y rehace el índice si el cliente lo alteró); mientras tanto, su dueño
podría cambiarla.

**`nivel_precio` y `condicion_pago` son campos independientes.** Una empresa
puede tener precio mayorista y pagar al contado — de hecho será el caso
mayoritario al inicio, porque la evaluación crediticia no debe frenar la primera
venta. Acoplarlos ahora obliga a desacoplarlos después.

### Vínculo con la orden

Al crear el checkout se fija en su `metadata`:

```
company_id
rut
razon_social
```

**Se guarda copia, no referencia.** Si la empresa cambia de razón social, las
facturas históricas no deben cambiar: un documento tributario refleja los datos
al momento de la compra. Guardar solo `company_id` produce facturas incorrectas
de forma silenciosa meses después.

No se crea una entidad de órdenes B2B. Facturación lee el RUT y la razón social
desde la orden existente.

## Flujos

### 1. Registro

```
RUT → validación módulo 11 → normalización → datos mínimos → en revisión → aprobada por el staff
```

La empresa nace **en revisión**: en el nivel por defecto
(`B2B_DEFAULT_NIVEL_PRECIO`, hoy `retail-cl`) y con `condicion_pago = contado`.
Ve la tabla de tramos del canal B2B, pero no puede comprar hasta que el equipo
de Ventu la aprueba (§ API, «Aprobar una empresa»).

**Aprobada = su `nivel_precio` es un canal de `B2B_CANALES`.** No hay un campo
aparte que pueda contradecirlo: aprobar es asignarle `b2b-cl` y revertir es
devolverla a `retail-cl`. El estado se copia a la clave pública
`ventu.b2b.estado` (`pendiente` | `aprobada`) solo porque la metadata pública es
lo único que Saleor deja filtrar, y sin ella listar las pendientes obligaría a
recorrer todos los clientes. Es un espejo: quien decide si puede comprar lee el
nivel, nunca el espejo.

**Por qué revisión manual** (decidido para el lanzamiento). El módulo 11 solo
prueba que el RUT está bien escrito, no que la empresa exista ni que quien se
registra la represente. Sin revisión, cualquiera con un RUT válido obtendría
precio mayorista y podría dejar pedidos por pagar. La revisión alarga el camino
a la primera compra, pero es el costo de no regalar el precio mayorista.

**El nivel no lo elige quien se registra**: si lo aceptara el alta, cualquiera se
asignaría precio mayorista. Por lo mismo, `B2B_DEFAULT_NIVEL_PRECIO` no debe ser
un canal B2B: toda empresa nacería aprobada. Un segundo alta del mismo usuario
responde 409: reescribiría el nivel asignado y el crédito aprobado.

**RUT ya registrado:** en el modelo 1:1 no hay resolución elegante, pero el caso
es frecuente (el colega de la misma empresa). El 1.0 debe responder con un
mensaje digno —«esta empresa ya está registrada, contáctanos»— y no un error
genérico. Es el caso que empujará la versión 1.1.

### 2. Cotización — el carrito es la cotización

No se construye un sistema de cotizaciones separado. **El carrito de Saleor
cumple esa función**: es simultáneamente la propuesta comercial editable y el
inicio de la transacción.

Verificado que Saleor lo soporta de forma nativa:

| Necesidad | Mecanismo | Verificado |
|---|---|---|
| Armar el carrito | `checkoutCreate` con `lines` y `metadata` | ✅ |
| **Precio negociado por línea** | `price` + `priceOverrideReason` en `CheckoutLineInput` | ✅ |
| Modificar cantidades | `checkoutLinesUpdate` / `checkoutLinesAdd` | ✅ |
| Asociarlo al cliente después | `checkoutCustomerAttach` | ✅ |
| Convertirlo en orden | `orderCreateFromCheckout` (pedido por pagar, § Compra) | ✅ |

El poder fijar precio por línea es lo que hace viable este enfoque: sin eso, un
carrito no podría expresar una condición negociada y haría falta una cotización
aparte.

Esto elimina el circuito de cotización en PDF → pedido → reingreso de productos
en el checkout. El cliente recibe siempre un enlace actualizado hacia la misma
intención de compra.

**Vigencia.** Un precio negociado no puede quedar vigente indefinidamente.
Persistir el carrito no significa congelar precio ni stock: ambos se revalidan
antes de cerrar. Toda cotización con precio negociado debe llevar vigencia
explícita.

### 3. Solicitud de crédito

Paso **voluntario y adicional**. No es requisito para crear cuenta ni para
comprar al contado.

```
"Solicitar crédito" → Ventu registra estado = pendiente
                    → Ventu recibe la Carpeta Tributaria
                    → la reenvía a Maxxa y borra su copia
                    → Maxxa evalúa; Ventu registra el resultado
```

**Ventu queda en la ruta del dato**, así que asume obligaciones de custodia sobre
el historial tributario del cliente. El diseño minimiza la ventana de exposición:

- Bucket **privado**, separado del de medios (que es público)
- **Borrado tras confirmar la entrega a Maxxa.** Recibir y reenviar no obliga a
  conservar: la retención por defecto es la mínima que permita reintentar el envío
- Acceso restringido a un rol acotado, con registro de cada acceso
- Retención máxima explícita en configuración, nunca implícita

Ventu almacena `credito_estado` y `credito_ref`; nunca el documento de forma
permanente. Esto acota la exposición frente a la Ley 21.719.

### 4. Compra

Sin cambios respecto del flujo actual, salvo la metadata de empresa en el
checkout y el canal correspondiente a su `nivel_precio`.

## Precios en 1.0

**Precio plano por canal, más tramos por cantidad.**

Pricing calcula un precio por canal (`compute_channel_prices`) y la empresa compra
en el canal indicado por su `nivel_precio`.

**IVA por canal.** `config.gross_for(channel)` decide si el canal publica con IVA
incluido: retail muestra el precio final al consumidor; B2B publica neto y el IVA
se detalla en la factura. Antes era un flag global y el canal mayorista habría
heredado el tratamiento de retail.

**Los tramos se cobran en la base del canal.** El precio de un tramo o uno
negociado se fija en la línea con `price`, y Saleor lo toma en la misma base en
que el canal ingresa sus precios (`taxConfiguration.pricesEnteredWithTax`): en
`b2b-cl`, **neto**, y le suma el IVA encima. Por eso la escalera —factores o
montos— se aplica sobre el neto, y el `precio_unitario` negociado de
`POST /cart` también va neto; calcularlo sobre el bruto cobraría el IVA dos
veces. `/tramos` y el incentivo muestran el tramo con IVA, como el precio de
lista junto al que aparecen, así que lo que se ve es lo que se cobra. Una tabla
de montos de Ventu 1.0 se lee como neta en `b2b-cl`: si venía con IVA, hay que
convertirla ([lanzamiento § d](lanzamiento.md#d-iva-en-b2b-cl)).

**Tramos por cantidad** (`pricing/tiers.py`). Saleor no tiene precios escalonados
—un channel-listing guarda un precio único por variante— pero sí admite fijar el
precio de una línea del carrito mediante `price` de `CheckoutLineInput`. El tramo
se resuelve en Pricing y se aplica a la línea.

```
1-9   → $100 c/u
10-49 →  $90 c/u
50+   →  $80 c/u
```

El tramo aplica a **todas** las unidades de la línea, no solo a las que exceden el
mínimo: es el modelo de la distribución mayorista. Consecuencia conocida y
deliberada: 9 unidades cuestan lo mismo que 10.

`siguiente_tramo()` permite incentivar la compra («lleva 3 más y pagas $90 c/u»).

**La escalera es por canal**, no por empresa (decidido). Vive en configuración
(`PRICING_TIERS_<SLUG>`) y se expresa en **factores**, no en montos:

```
PRICING_TIERS_B2B_CL="1:1.0,10:0.9,50:0.8"
```

Se usan factores para que una misma regla —«desde 10 unidades, 10% menos»— sirva
para todo el catálogo sin repetir precios producto por producto. Un canal sin
escalera definida simplemente no tiene tramos, lo que es configuración válida y
no un error.

**Manda la tabla del producto.** Ventu 1.0 define los tramos como montos
absolutos por producto —«este artículo, a 4 unidades, vale $8.900»— porque cada
monto es una decisión comercial y no siempre corresponde a un porcentaje redondo.
Ese es el caso principal; la escalera del canal es el último recurso. La
precedencia es: variante → producto → canal.

El precio por empresa queda para la fase 1.2.

### Dónde se guarda la escalera

En `privateMetadata` del producto (`ventu.pricing.tramos`), junto con el costo
(`ventu.pricing.costo`). **No en `metadata`**: la metadata de producto de Saleor
se lee sin autenticación, así que publicar ahí la escalera la dejaría a la vista
de cualquiera —un cliente retail, un competidor— y el costo quedaría directamente
expuesto.

La contrapartida es de permisos: leer metadata privada exige `MANAGE_PRODUCTS`,
que es escritura sobre todo el catálogo. Para no ampliar los permisos de la App
B2B entera, la lectura se firma con `SALEOR_PRODUCTS_TOKEN`; vacío usa el token
propio de la app.

### Quién ve la tabla

`GET /tramos/{variant_id}?user_id=…` es el único camino por el que la escalera
sale de la App B2B, y responde con cifras **solo** si detrás de la sesión hay una
empresa registrada:

| Sesión | Respuesta |
|---|---|
| Anónima | `{"visible": false, "motivo": "sin_identificar"}` |
| Cliente retail | `{"visible": false, "motivo": "sin_empresa"}` |
| Empresa registrada, fuera de un canal B2B | `{"visible": false, "motivo": "canal_no_b2b"}` |
| Empresa registrada | `{"visible": true, "rut", "canal", "tramos": [...]}` |

El canal es el del parámetro `canal` (el del carrito) o, sin él, el nivel de la
empresa. Fuera de `B2B_CANALES` el carrito cobra precio de lista —el reprecio
no corre ahí—, así que mostrar la tabla prometería un precio que no se cobra.

Siempre **200**, nunca 403: que un cliente retail sepa que existe una tabla que
no puede ver no le aporta nada y sí invita a buscarla.

La respuesta lleva `desde` y `precio_unitario`, nada más. El costo y el margen no
salen de la app **ni siquiera para la empresa registrada** — hay una prueba que
busca esas palabras en el cuerpo crudo de la respuesta.

### El stock condiciona la tabla

Ofrecer «50 unidades a $8.400» con 12 en bodega es una promesa que el checkout va
a rechazar: el cliente arma el pedido y recién ahí descubre que no hay. Peor en
B2B, donde la cantidad es el motivo de la compra.

- Los tramos por sobre el stock disponible se descartan.
- Bajo `B2B_STOCK_MINIMO_TRAMOS` no se publica tabla alguna.
- Si la consulta no trae dato de stock, **no se filtra**: es preferible mostrar
  la tabla que ocultarla por una respuesta incompleta.

### Dónde se muestra

En la ficha de producto del storefront, dentro de la caja de compra. El
storefront no lee la escalera de Saleor: pregunta a la App B2B con el id de
sesión resuelto en el servidor y pinta lo que reciba. Para cualquier otra sesión
el componente no llega a renderizarse, así que la tabla tampoco viaja en el HTML.

Requiere `B2B_APP_URL` en el storefront. Sin esa variable la tienda funciona
igual, solo que sin tabla. La consulta tiene un presupuesto de 2,5 s y cualquier
fallo se trata como «sin tabla»: la ficha nunca muestra un error por esto.

La tabla es informativa. El precio de compra lo resuelve la cantidad del
carrito, como en el sitio actual.

## El recorrido completo en 1.0

Registrarse → ver el catálogo → precio por volumen → elegir medio de pago →
comprar. Cada paso, y lo que lo condiciona:

**1. Registro con RUT.** `/signup` pide razón social y RUT junto con la cuenta.
El alta de la empresa la hace el servidor con el id que devuelve
`accountRegister`, nunca con uno que venga del navegador: aceptarlo del cliente
permitiría asociar una empresa a la cuenta de otra persona. Si el alta falla, la
cuenta igual quedó creada —deshacerla dejaría el correo tomado sin poder
reintentar— y se completa después en `/empresa`.

El dígito verificador lo valida la App B2B (módulo 11): una sola implementación,
y del lado que no se puede saltar. La empresa queda en revisión hasta que el staff
la aprueba (§ Registro); `GET /company/de-usuario` lo informa con `aprobada` y
`estado`.

**2. Catálogo reservado.** Los canales listados en `B2B_CHANNELS` redirigen a
`/login` a quien no tiene sesión y a `/empresa` a quien tiene cuenta pero no
empresa.

> Es una **puerta comercial, no un límite de seguridad**: los canales de Saleor
> son consultables por la API sin autenticación, así que quien conozca el slug
> puede leer los precios por su cuenta. Lo que sí queda protegido es la escalera
> de tramos y el costo, que viven en metadata privada. La distinción importa
> para no confundir «no se llega sin identificarse» con «es secreto».

Si Saleor no responde, la puerta **deja pasar**: cerrarle el catálogo a un
cliente registrado por una caída ajena sería peor, y los precios del canal ya son
públicos.

**3. Precio por volumen.** La tabla en la ficha de producto (§ Precios en 1.0).

**4. Medios de pago.** Cuando quien compra es una empresa, el paso de pago
reemplaza la caja de pasarelas por los medios de Ventu:

| Medio | Estado | Condición |
|---|---|---|
| Tarjeta de crédito | Se ofrece, no conectada | — |
| Tarjeta de débito | Se ofrece, no conectada | — |
| Transferencia bancaria | Operativa | — |
| Cheke Maxxa 30 días | Operativa | Crédito aprobado |

Los medios que no están conectados **se muestran igual**, deshabilitados y con el
motivo. Una empresa en revisión los ve **todos** deshabilitados, con motivo
`pendiente_aprobacion`. Una vitrina que solo lista lo que funciona no le dice a la empresa qué va
a poder usar, ni por qué le conviene pedir crédito. Y el medio se valida en el
servidor antes de tocar Saleor: si no corresponde, el carrito queda intacto para
que elija otro.

**5. Compra.** `POST /pedido` usa `orderCreateFromCheckout` y no
`checkoutComplete`. `checkoutComplete` exige que el total esté cubierto —regla
correcta para una venta al consumidor, equivocada para una venta a 30 días—.
El pedido nace **por pagar** (`ventu.pago.estado = pendiente`) y eso es su
condición normal, no una anomalía: en distribución mayorista la orden se despacha
contra una promesa de pago.

El id del checkout se toma de la cookie del canal y el del usuario de la sesión;
ninguno del cuerpo de la petición. La App B2B igual verifica que el carrito sea
de ese usuario antes de tocarlo. La secuencia completa está en § API.

### Valores de maqueta

En esta etapa el recorrido está completo pero hay cifras y conexiones que son
**placeholders explícitos**, no decisiones comerciales. Quedan listadas aquí para
que nadie las tome por definitivas:

| Qué | Valor de maqueta | Qué falta |
|---|---|---|
| Escalera de tramos | 1 / 6 / 12 / 24 con −10%, −18%, −25% | la escalera real por producto |
| Costo publicado | precio neto ÷ 1,55 | el costo real de compra |
| Envío mayorista | $3.990 plano, igual que retail | la tarifa mayorista |
| Webpay | ambiente de integración, credenciales públicas de prueba | contrato y credenciales productivas |
| IVA | no configurado; en B2B el total es neto | clase y tasa del 19% para la factura |

### Lo que falta para operar de verdad

- **Confirmación de cuenta por correo.** Saleor tiene
  `enableAccountConfirmationByEmail` activo: sin envío de correos configurado,
  una cuenta recién creada no puede iniciar sesión. Decisión pendiente: conectar
  el correo o desactivar la confirmación ([lanzamiento § e](lanzamiento.md#e-correo-de-confirmación-de-cuenta)).
- **Pasarela de tarjetas** (Webpay). Hasta entonces los dos medios de tarjeta se
  muestran deshabilitados.
- **Cobro y conciliación** de la transferencia, y el envío del pedido a Maxxa.

## Dónde vive el código

App independiente `apps/ventu-b2b`, siguiendo el molde de `apps/ventu` y
`apps/ventu-pagos`: FastAPI, manifiesto propio, webhooks de Saleor.

Se mantiene separada de `apps/ventu` por **privilegio mínimo**: requiere
`MANAGE_USERS` para escribir la metadata del cliente, permiso que las apps
actuales no tienen ni necesitan.

## Auditoría

Los estados viven en metadata, que se sobrescribe y no conserva historial. Por
eso cada cambio se **anexa** además a una lista JSON en la metadata privada del
usuario, acotada a las últimas 50 entradas:

| Clave | Qué registra |
|---|---|
| `ventu.b2b.credito_log` | cada transición de crédito: hora, `desde>hacia`, motivo, referencia de Maxxa, actor |
| `ventu.b2b.company_log` | cada cambio del staff: hora, actor, `{campo: [antes, después]}`; incluye aprobar y revertir, que son cambios de `nivel_precio` |
| `ventu.b2b.alta` | fecha del alta de la empresa (UTC); `/company/pendientes` la muestra como `empresa_registrada` |

La hora la fija el servidor (UTC); la que envíe quien llama se ignora. El actor
lo declara la herramienta interna, porque el token de staff es compartido.

**No es append-only de verdad**: quien tenga `MANAGE_USERS` puede reescribir la
clave, y dos escrituras simultáneas pueden pisarse. Al volumen del MVP responde
«¿por qué esta empresa tiene crédito aprobado?» sin sumar una base de datos; un
registro inalterable queda para la migración a tabla propia.

## API

### Acceso

Toda ruta que toca datos exige `Authorization: Bearer <token>`. Hay dos tokens
porque hay dos llamadores con confianza distinta:

| Token | Lo usa | Rutas |
|---|---|---|
| `B2B_SERVICE_TOKEN` | el **servidor** del storefront, en nombre del cliente | `GET /company/de-usuario/{user_id}`, `POST /company`, `GET /tramos/{variant_id}`, `POST /cart/reprecio`, `GET /cart/{link_id}`, `POST /pedido`, `POST /credito/solicitar`, `POST /credito/carpeta` |
| `B2B_STAFF_TOKEN` | herramientas internas de Ventu | `GET /company/pendientes`, `GET /company/por-rut/{rut}`, `PATCH /company/{user_id}`, `POST /credito/resolver`, `POST /cart` (admite precio negociado) |

- El token de staff también sirve en las rutas del cliente; el de servicio
  **no** sirve en las de staff: filtrarlo no debe permitir aprobarse crédito ni
  asignarse precio mayorista.
- `user_id` sigue llegando en el cuerpo o la URL. El token de servicio equivale a
  «el storefront ya autenticó a este usuario»: nunca debe viajar al navegador.
  En el storefront se configura como `B2B_APP_TOKEN` y debe ser igual a
  `B2B_SERVICE_TOKEN`.
- Ambos vacíos: la API queda **cerrada**. Toda ruta con datos responde 503
  «la API no tiene credenciales configuradas» y el arranque lo registra como
  error. Antes quedaba abierta, y un deploy que perdiera las variables
  publicaba la API entera sin que nada fallara a la vista.
- Para desarrollo local, `B2B_AUTH_ABIERTA=1` la abre mientras no haya ningún
  token, con aviso en el log. Con un token configurado no tiene efecto. No se
  configura en Railway.
- Con al menos uno configurado, una ruta cuyo token está vacío queda cerrada
  (401): configurar solo el de servicio no deja abiertas las de staff.
- Siempre abiertas: `/health`, `/manifest`, `/register` (Saleor y el healthcheck
  no tienen nuestras credenciales). `/docs`, `/redoc` y `/openapi.json` solo
  se publican con la API abierta a pedido (`B2B_AUTH_ABIERTA=1` y sin tokens).

### Variables de entorno nuevas

| Variable | Por defecto | Para qué |
|---|---|---|
| `B2B_SERVICE_TOKEN` | vacío | token del storefront (ver arriba) |
| `B2B_STAFF_TOKEN` | vacío | token de las herramientas internas |
| `B2B_AUTH_ABIERTA` | vacío | `1` abre la API sin tokens; solo desarrollo local, sin efecto si hay un token |
| `B2B_CANALES` | `b2b-cl` | canales (separados por coma) donde `POST /pedido` acepta un carrito |
| `B2B_NIVELES_PERMITIDOS` | `retail-cl,b2b-cl` | niveles que el staff puede asignar con `PATCH` |
| `B2B_INSTRUCCIONES_TRANSFERENCIA` | vacío | datos bancarios que `POST /pedido` devuelve al pagar por transferencia; vacío = `null` |
| `B2B_PUBLIC_URL` | vacío | URL pública del manifest (p. ej. `https://b2b.ventu.cl`); sin ella se usa `X-Forwarded-Proto`/`X-Forwarded-Host`, y https salvo en localhost |

**Arranque detrás del proxy.** El `Dockerfile` arranca uvicorn con
`--proxy-headers --forwarded-allow-ips='*'`: la IP del proxy de Railway no es
fija, y uvicorn por defecto solo confía en `127.0.0.1`, así que ignoraría
`X-Forwarded-Proto`/`X-Forwarded-For`. Si Railway construye el servicio con
Railpack, el Dockerfile no se usa y el *Start Command* debe ser el mismo
([lanzamiento § a](lanzamiento.md#a-tokens-de-la-app-b2b)). La URL del manifest
no depende de esto: la app lee esos encabezados por su cuenta.

`B2B_MARKUP_MINIMO` ya existía; ahora además **bloquea**: `POST /cart` con un
precio negociado bajo el piso responde 422 con el detalle, salvo que se reenvíe
con `"forzar": true`.

### Cambiar condiciones de una empresa

`PATCH /company/{user_id}` (staff). Todos los campos son opcionales; se escriben
solo los que cambian y cada cambio queda en `ventu.b2b.company_log`.

```bash
curl -X PATCH "https://b2b.ventu.cl/company/VXNlcjoxMjM=" \
  -H "Authorization: Bearer $B2B_STAFF_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"nivel_precio": "b2b-cl", "condicion_pago": "credito_30", "actor": "staff@ejemplo.cl"}'
```

| Campo | Validación |
|---|---|
| `nivel_precio` | debe estar en `B2B_NIVELES_PERMITIDOS` |
| `condicion_pago` | `contado` \| `credito_30` |
| `razon_social`, `giro`, `telefono` | razón social no vacía |
| `actor` | quién hizo el cambio; solo va al historial |

Responde lo mismo que `GET /company/de-usuario/{user_id}`, con `aprobada` y
`estado`. 404 si el usuario no tiene empresa; 422 si el cuerpo no trae ningún
campo o un valor no es válido. El RUT no se edita: cambiarlo sería otra empresa.

### Aprobar una empresa

Aprobar es un `PATCH` que lleva `nivel_precio` a un canal de `B2B_CANALES`:

```bash
curl -X PATCH "https://b2b.ventu.cl/company/VXNlcjoxMjM=" \
  -H "Authorization: Bearer $B2B_STAFF_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"nivel_precio": "b2b-cl", "actor": "staff@ejemplo.cl"}'
```

Todo `PATCH` que toca `nivel_precio` actualiza el espejo público
`ventu.b2b.estado`. Primero escribe la metadata privada y después el espejo: si
la segunda escritura falla, lo peor que pasa es que una empresa ya aprobada siga
listada como pendiente. El orden inverso podría esconder de la lista a una
empresa que sigue en revisión.

**Empresas anteriores al espejo.** No tienen `ventu.b2b.estado`: se leen bien
(el estado se deriva del nivel), pero **no aparecen** en `/company/pendientes`.
Para repararlas, reenvía su nivel actual. Si solo falta el espejo, se escribe
solo el espejo, sin tocar condiciones ni el historial.

### `GET /company/pendientes`

Empresas en revisión, las más antiguas primero (staff):

```bash
curl -s "https://b2b.ventu.cl/company/pendientes" \
  -H "Authorization: Bearer $B2B_STAFF_TOKEN"
```

```
{"empresas": [{user_id, email, nombre, rut, razon_social, giro, telefono,
               nivel_precio, cuenta_creada, empresa_registrada,
               correo_confirmado, activa}, …],
 "total": N, "truncado": false}
```

- Filtra en Saleor por el espejo público (`ventu.b2b.estado = pendiente`), de a
  100 por página y hasta 10 páginas. Si hay más, responde `truncado: true` y un
  `aviso`: se aprueban las que se ven y se vuelve a consultar.
- Vuelve a comprobar el nivel de cada fila y omite las que el nivel ya da por
  aprobadas: un espejo atrasado no hace aparecer como pendiente a una empresa
  aprobada. También omite, con aviso en el log, las filas cuya empresa no se
  puede leer.
- Las empresas anteriores al espejo no aparecen (ver arriba).

### `POST /pedido`, paso a paso

Todo lo que puede rechazar el pedido va antes de la primera escritura, y la
orden se crea al final y una sola vez:

1. **Lee el checkout.** 404 si no existe.
2. **Dueño.** 403 si `checkout.user.id` no es el `user_id` recibido.
3. **Canal.** 422 si no está en `B2B_CANALES`: un pedido por pagar en retail es
   una venta que nadie espera cobrar.
4. **Empresa aprobada y medio.** 403 sin empresa; 403 si la empresa está en
   revisión, con el detalle «Tu empresa está en revisión. Te avisaremos cuando
   esté habilitada para comprar.». Esto se comprueba antes de cualquier
   escritura: el carrito queda intacto para cuando la aprueben. 409 si el medio
   no corresponde (p. ej. Maxxa sin crédito aprobado).
5. **Cantidades negociadas.** 409 `CARRITO_MODIFICADO` si una línea con precio
   negociado ya no tiene la cantidad acordada (ver «Qué líneas toca el
   reprecio»).
6. **Reprecio en el servidor**, con el canal del checkout. Si falla: 502 y **no
   se crea la orden**; cobrar un precio que no se pudo confirmar es peor que
   pedir que se reintente.
7. **Facturación.** Si falta, se copia la dirección de despacho con
   `checkoutBillingAddressUpdate`; sin ninguna de las dos, 422. Si Saleor
   rechaza la dirección como facturación, también 422.
8. **Relectura.** El carrito se vuelve a leer justo antes de crear la orden:
   409 `CARRITO_MODIFICADO` si una cantidad cambió desde el paso 1 (otra
   pestaña, el carrito lateral), porque el precio fijado era para la cantidad
   anterior y Saleor lo conservaría igual; 409 `CHECKOUT_NOT_FOUND` si ya no
   existe. Queda una ventana de una consulta, no la de todo el flujo.
9. **`orderCreateFromCheckout`**, nunca reintentado. Si Saleor rechaza la orden,
   responde 409 o 422 con su código (tabla abajo). Si no responde a tiempo, 504
   «revisa tus pedidos antes de intentarlo de nuevo», porque la orden pudo
   haberse creado.

La respuesta agrega `instrucciones_pago` (`B2B_INSTRUCCIONES_TRANSFERENCIA` si
el medio es transferencia; si no, `null`).

**Rechazos con código.** Los rechazos de los pasos 3, 4, 5, 7, 8 y 9 responden
`{"detail": "<castellano>", "code": "<CÓDIGO>"}`. El detalle se puede mostrar
tal cual y el código sirve para decidir en el storefront. El error crudo de
Saleor, en inglés y con nombres de campos internos, va **solo al log**.

| `code` | HTTP | Cuándo |
|---|---|---|
| `CANAL_NO_B2B` | 422 | el carrito no está en `B2B_CANALES` |
| `SIN_EMPRESA` | 403 | el usuario no tiene empresa |
| `PENDIENTE_APROBACION` | 403 | la empresa aún no está aprobada (el mismo motivo que deshabilita sus medios de pago) |
| `MEDIO_NO_DISPONIBLE` | 409 | el medio no corresponde a esta empresa |
| `CARRITO_MODIFICADO` | 409 | una línea negociada ya no tiene la cantidad acordada, o una cantidad cambió mientras se confirmaba el pedido |
| `SHIPPING_ADDRESS_NOT_SET` | 422 | el carrito no tiene dirección de despacho ni de facturación |
| `BILLING_ADDRESS_INVALID` | 422 | Saleor no aceptó la dirección de despacho como facturación |
| `INSUFFICIENT_STOCK`, `UNAVAILABLE_VARIANT_IN_CHANNEL`, `CHANNEL_INACTIVE`, `VOUCHER_NOT_APPLICABLE`, `GIFT_CARD_NOT_APPLICABLE`, `INVALID_SHIPPING_METHOD`, `TAX_ERROR`, `CHECKOUT_NOT_FOUND` | 409 | Saleor rechazó la orden: el carrito está bien armado, pero algo cambió desde que se armó. `CHECKOUT_NOT_FOUND` sugiere revisar los pedidos, porque la orden pudo haberse creado ya; también responde así si el carrito desaparece en el paso 8 |
| `SHIPPING_METHOD_NOT_SET`, `SHIPPING_ADDRESS_NOT_SET`, `BILLING_ADDRESS_NOT_SET`, `EMAIL_NOT_SET`, `NO_LINES` | 422 | Saleor rechazó la orden porque al carrito le falta algo que el cliente puede completar |
| otro código de Saleor | 422 | se entrega el código tal cual, con un detalle genérico |
| `ORDEN_RECHAZADA` | 422 | Saleor rechazó la orden sin código |

`CANAL_NO_B2B`, `SIN_EMPRESA`, `PENDIENTE_APROBACION`, `MEDIO_NO_DISPONIBLE`,
`CARRITO_MODIFICADO`, `BILLING_ADDRESS_INVALID` y `ORDEN_RECHAZADA` son códigos
propios; los demás son
los de `OrderCreateFromCheckoutErrorCode` de Saleor. Siguen respondiendo solo
`{"detail"}`: 404 (el checkout no existe), 403 (el carrito es de otro usuario),
502 (falló el reprecio, o Saleor respondió algo que no se entiende) y 504.

`POST /cart/reprecio` aplica el mismo reprecio para mostrar el total en el
carrito: verifica el dueño (403), usa el canal del checkout, devuelve al precio
de lista (`price: null`) una línea que ya no alcanza ningún tramo y nunca toca un
precio negociado por el staff. Un fallo responde 502 en vez de `aplicado: false`.
Si el canal del checkout (el de Saleor, no uno que diga quien llama) no está en
`B2B_CANALES`, responde `{"aplicado": false, "motivo": "canal_no_b2b"}` sin tocar
nada. Las líneas se actualizan sin `quantity`: con ella Saleor revalida stock y
disponibilidad, y un producto agotado haría fallar el reprecio con un 502 en vez
de llegar al pedido, que lo responde como un 409 legible.

**Qué líneas toca el reprecio.** Solo las que no tienen motivo
(`priceOverrideReason`) o tienen el del tramo, «Precio por volumen». Esas se
recalculan o, si ya no alcanzan ningún tramo, vuelven al precio de lista. Una
línea con **cualquier otro** motivo se respeta tal cual: «Precio negociado
(B2B) x500», que escribe `POST /cart`, o el motivo que usaban versiones
anteriores para los tramos. Así, un carrito mixto conserva lo negociado y ajusta solo los
tramos. Límite: un precio fijado **sin** motivo, desde fuera de la app, no se
distingue de una línea sin precio fijado, y el reprecio lo trata como tal.

**La cantidad negociada va en el motivo.** Saleor conserva el precio fijado
cuando el cliente cambia solo la cantidad: sin control, 500 unidades a precio
negociado se podían cerrar como 1 al mismo precio. `POST /cart` escribe
`Precio negociado (B2B) x<cantidad>` y `POST /pedido` rechaza con
`CARRITO_MODIFICADO` la línea que ya no la tiene. Va en el motivo y no en la
metadata de la línea porque el motivo solo lo escribe una app, y la metadata
de la línea la puede escribir el cliente. Un motivo negociado sin cantidad
(carritos anteriores a este cambio) se respeta sin verificarla.

### Errores de Saleor

El cliente de Saleor corta a los 10 s y reintenta **solo lecturas**, hasta 2
veces; las mutaciones no se reintentan nunca. Un fallo de Saleor responde 502 y
un timeout 504, ambos con detalle en castellano; el error interno queda en el
log (stdout), con la plantilla de la ruta y no la URL, que lleva `user_id`.

## Fuera del 1.0

Explícitamente excluido, para que el alcance no se erosione:

- Múltiples usuarios, roles o membresías por empresa
- Centros de costo y flujos de aprobación interna
- Sucursales de empresa
- Motor propio de scoring crediticio
- Precio negociado por empresa

## Dependencias

| Dependencia | Estado |
|---|---|
| Canal B2B en Saleor | ✅ Creado (`b2b-cl`, CLP, warehouse Ventu) |
| `pricesEnteredWithTax=false` en `b2b-cl` | ⏳ Pendiente: el token de la app carece de `MANAGE_TAXES`; se hace a mano en el dashboard ([lanzamiento § d](lanzamiento.md#d-iva-en-b2b-cl)) |
| Integración Maxxa | Pendiente. Misma forma que `ventu-pagos` (Transaction API) |
| Facturación electrónica (DTE) | Pendiente. Requisito legal para vender a empresas |

---

# Roadmap — B2B 1.1 y posteriores

Registro de funcionalidades futuras. El orden es indicativo; la prioridad real
debe surgir de la evidencia de uso, no de la anticipación.

## 1.1 — Empresa multiusuario

*Detonante esperado: el caso «mi colega ya registró la empresa».*

- Múltiples usuarios asociados a una misma Company
- Roles básicos: comprador / administrador
- Invitación de usuarios por parte del administrador
- Migración del modelo 1:1 — de `privateMetadata` a tabla propia

## 1.2 — Precio por empresa cliente

*Etapa siguiente acordada tras el precio plano por canal.*

- Precio negociado por empresa, más fino que el canal
- Escalera de tramos **por empresa** (el motor de tramos ya existe en 1.0;
  lo que falta es que la escalera varíe por cliente)
- Reglas de cantidad: mínimos de compra, múltiplos, venta por caja
- Vigencia de precios acordados

> Resuelto en 1.0: los tramos se calculan en `pricing/tiers.py` y se aplican a la
> línea del carrito vía `price` de `CheckoutLineInput`. Lo que queda para 1.2 es
> que la escalera dependa de la empresa y no del canal.

## 1.3 — Operación de compra

- Número de orden de compra (OC) del cliente en el checkout
- Listas de requisición y recompra rápida
- Historial y reportes de compra por empresa
- Exportación de compras para conciliación

## 1.4 — Crédito avanzado

- Cupo disponible visible para el cliente
- Consumo de la línea en tiempo real
- Condiciones múltiples (Net 7 / 15 / 60 / fecha fija)
- Carpeta Tributaria automatizada mediante mandato ante el SII
- Renovación y revisión periódica de líneas

## 1.5 — Estructura corporativa

*Solo si la evidencia lo justifica. Gran parte del mercado objetivo no lo usará.*

- Sucursales de empresa, con dirección y condiciones propias
- Centros de costo
- Flujos de aprobación interna por monto
- Jerarquía de empresas (matriz / filiales)

## 1.6 — Integración con clientes grandes

- API de compra para clientes con sistemas propios
- Punch-out / EDI
- Catálogo sindicado

## Transversal

- Auditoría completa de decisiones comerciales y crediticias
- Migración del almacenamiento de Company a tabla propia
- Métricas de conversión del embudo B2B (registro → primera compra → crédito)
