# Ventu 2.0 — App B2B

Especificación de la App B2B y registro de funcionalidades futuras.

| Versión | Estado | Contenido |
|---|---|---|
| **B2B 1.0** | Especificada | MVP: identificar empresa, cotizar, solicitar crédito, comprar |
| **B2B 1.1+** | Registro | Backlog de funcionalidades futuras (§ Roadmap) |

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
```

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
RUT → validación módulo 11 → normalización → datos mínimos → cuenta activa
```

La empresa queda operativa de inmediato, con `nivel_precio` asignado y
`condicion_pago = contado`.

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
| Convertirlo en orden | `checkoutComplete` | ✅ |

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
| Empresa registrada | `{"visible": true, "rut", "canal", "tramos": [...]}` |

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
y del lado que no se puede saltar.

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
motivo. Una vitrina que solo lista lo que funciona no le dice a la empresa qué va
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
ninguno del cuerpo de la petición.

### Lo que falta para operar de verdad

- **Confirmación de cuenta por correo.** Saleor tiene
  `enableAccountConfirmationByEmail` activo: sin envío de correos configurado,
  una cuenta recién creada no puede iniciar sesión. Decisión pendiente: conectar
  el correo o desactivar la confirmación.
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

Los estados viven en metadata, que se sobrescribe y no conserva historial. Una
decisión de crédito es financieramente consecuente: cada cambio de
`credito_estado` debe además quedar en un registro **append-only**.

Sin esto, la pregunta «¿por qué esta empresa tiene crédito aprobado?» no tiene
respuesta.

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
| `pricesEnteredWithTax=false` en `b2b-cl` | ⏳ Pendiente: el token de la app carece de `MANAGE_TAXES` |
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
