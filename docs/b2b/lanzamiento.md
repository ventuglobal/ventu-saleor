# Lanzamiento B2B — lista de verificación

Qué hay que hacer, en qué orden y cómo comprobarlo para abrir la compra B2B en
producción. El porqué del diseño está en el [README](README.md); aquí van los
pasos.

> **Ningún secreto va en este documento, en un ticket ni en un chat.** Los
> tokens se generan en tu terminal y se pegan directo en las variables del
> servicio en Railway. Todo lo que aparece como `$VARIABLE` o `<algo>` es un
> marcador que se reemplaza en tu terminal, nunca aquí.

| Marcador | Qué es |
|---|---|
| `$B2B_URL` | URL pública de ventu-b2b, p. ej. `https://<dominio-de-ventu-b2b>` |
| `$B2B_STAFF_TOKEN` | token de staff de ventu-b2b (§ a) |
| `$SALEOR_STAFF_JWT` | token de un usuario staff de Saleor con el permiso que se indique |
| `<dominio-del-storefront>` | host público del storefront, sin `https://` |
| `<dominio-del-dashboard>` | host público del dashboard de Saleor |
| `<dominio-de-la-api>` | host público de `saleor-api` |
| `<user_id>` | id de Saleor del usuario (`VXNlcjo…`) |

Los pasos a–f son configuración y van antes de abrir el registro. Los pasos g y
h son la operación y la prueba final.

---

## a. Tokens de la App B2B

La versión desplegada hoy responde a cualquiera: sin tokens su API queda
abierta, y cualquiera podría asignarse precio mayorista o aprobarse crédito. Se
cierra con **dos** tokens distintos, porque hay dos llamadores con distinta
confianza.

**Desde esta versión, sin tokens ventu-b2b queda cerrada**: toda ruta con datos
responde 503 y el log de arranque lo registra como error. Configura sus
variables (paso 3) antes de desplegarla o en el mismo deploy; si no, el checkout
B2B queda caído hasta que estén. `B2B_AUTH_ABIERTA` no se configura en Railway:
abre la API sin tokens y es solo para desarrollo local.

1. Genera dos valores, cada uno con:

   ```bash
   openssl rand -hex 32
   ```

   Uno es el **token de servicio**, que comparten el storefront y ventu-b2b. El
   otro es el **token de staff**, que usan solo las herramientas internas.
   Guarda el de staff en el gestor de contraseñas del equipo: es el que
   aprueba empresas.

2. **Variables primero, en los dos servicios**, antes de desplegar este código.
   La versión desplegada hoy no las lee —ni el storefront manda token ni
   ventu-b2b lo exige—, así que cargarlas no cambia nada todavía.

   Storefront:

   | Variable | Valor |
   |---|---|
   | `B2B_APP_TOKEN` | el token de servicio |
   | `B2B_CHANNELS` | `b2b-cl` |

   Aprovecha de comprobar que `B2B_APP_URL` apunta a `$B2B_URL`.

   ventu-b2b:

   | Variable | Valor |
   |---|---|
   | `B2B_SERVICE_TOKEN` | el **mismo** token de servicio |
   | `B2B_STAFF_TOKEN` | el token de staff |
   | `B2B_CANALES` | `b2b-cl` |
   | `B2B_PUBLIC_URL` | `$B2B_URL`, sin `/` final |

3. **Después el código**: ventu-b2b primero y el storefront apenas termine.

**Por qué en este orden.** Con las variables ya puestas, cada servicio arranca
con su credencial desde el primer segundo. Entre un deploy y otro queda una
ventana corta:

- ventu-b2b nuevo con el storefront viejo: el storefront todavía no manda el
  token y todo responde 401. La ficha pierde la tabla de tramos y el pago B2B
  no funciona hasta que termina el deploy del storefront.
- Storefront nuevo con ventu-b2b viejo: el backend todavía no informa
  `aprobada`, y el storefront lo lee como «en revisión». Toda empresa ve el
  aviso y no puede cerrar pedidos, pero nada queda expuesto.

Por eso los dos deploys van seguidos. Desplegar ventu-b2b **sin** sus
variables es lo único que deja todo caído: responde 503 hasta que se cargan.

**Por qué `B2B_PUBLIC_URL`.** Saleor no instala una app que se anuncia por
`http`. Detrás del proxy de Railway, el proceso recibe las peticiones por http.
Sin esta variable, la app deduce la URL de los encabezados del proxy; con ella,
no depende de eso.

**Arranque detrás del proxy.** El `Dockerfile` arranca uvicorn con
`--proxy-headers --forwarded-allow-ips='*'`. Si Railway construye el servicio con
Railpack y no con el Dockerfile, ese comando no se usa. En ese caso, revisa en
*Settings → Deploy* que el *Start Command* sea el mismo:

```
sh -c "uvicorn ventu_b2b.main:app --host 0.0.0.0 --port ${PORT:-8100} --proxy-headers --forwarded-allow-ips='*'"
```

**Comprobación**, ya con los tokens puestos:

```bash
curl -s -o /dev/null -w '%{http_code}\n' "$B2B_URL/health"               # 200: siempre abierta
curl -s -o /dev/null -w '%{http_code}\n' "$B2B_URL/company/pendientes"   # 401: sin token (503: ventu-b2b sin tokens)
curl -s -o /dev/null -w '%{http_code}\n' "$B2B_URL/docs"                 # 404: el esquema ya no se publica
curl -s -o /dev/null -w '%{http_code}\n' "$B2B_URL/company/pendientes" \
  -H "Authorization: Bearer $B2B_STAFF_TOKEN"                            # 200
curl -s "$B2B_URL/manifest" | jq -r .tokenTargetUrl                      # https://…/register
```

En el log de arranque de ventu-b2b no debe aparecer el aviso «la API queda
ABIERTA» ni el error «toda ruta con datos responde 503».

---

## b. `ALLOWED_CLIENT_HOSTS` antes de `DEBUG=False`

Si `DEBUG` no está definida, Saleor 3.23 arranca con `DEBUG=True`, que muestra
trazas internas en los errores. Hay que apagarlo, pero con `DEBUG=False` Saleor
exige `ALLOWED_CLIENT_HOSTS` y, **sin esa variable, no arranca**
(`ImproperlyConfigured`). Esto vale para `saleor-api` y también para
`saleor-worker`, que carga la misma configuración.

1. Configura en `saleor-api` **y** en `saleor-worker`:

   ```
   ALLOWED_CLIENT_HOSTS=<dominio-del-storefront>,<dominio-del-dashboard>
   ```

   Son hosts separados por coma, sin esquema. Saleor valida contra esta lista
   las URLs de retorno de los correos de confirmación de cuenta y de
   restablecimiento de contraseña, tanto las del storefront como las del
   dashboard. Si el storefront también responde con `www.`, agrega ese host.
2. Despliega ambos servicios y comprueba que arrancan.
3. Recién entonces pon `DEBUG=False` en los dos y vuelve a desplegar.

**Comprobación:** `https://<dominio-de-la-api>/graphql/` responde, el worker
queda en ejecución y crear una cuenta en el storefront sigue funcionando.

---

## c. Gateway Dummy

- **`b2b-cl`: ya está desactivado.** La compra B2B no pasa por una pasarela:
  `POST /pedido` crea la orden por pagar con `orderCreateFromCheckout`. Nada del
  flujo B2B depende del Dummy.
- **`retail-cl`: también está desactivado** (27-09-2026). Con el Dummy activo,
  cualquiera podía completar una compra retail con un pago simulado que Saleor
  registraba como cobrado: una orden que parece pagada sin que haya entrado
  dinero. Era el único medio de pago del canal, así que **el checkout retail no
  ofrece ningún medio de pago hasta conectar una pasarela real** (Webpay).

Para verificarlo, `availablePaymentGateways` debe devolver `[]` en ambos canales:

```bash
curl -s "https://<dominio-de-la-api>/graphql/" -H 'content-type: application/json' \
  -d '{"query":"{ shop { availablePaymentGateways(channel: \"retail-cl\") { id } } }"}'
```

Para reactivarlo en un canal (solo pruebas): Dashboard → *Configuration →
Plugins* → *Dummy*, elige el canal y márcalo activo.

---

## d. IVA en `b2b-cl`

Pricing publica precios **netos** en `b2b-cl`, porque en B2B el IVA va
desglosado en la factura (`config.gross_for`). Si Saleor tomara esos montos como
precios con IVA incluido, cobraría el neto como total. Ventu absorbería el IVA
—cerca de un 16 % menos de ingreso— sin que nada falle a la vista.

La app no tiene `MANAGE_TAXES`, así que esto lo hace una persona del staff en
el dashboard, *Configuration → Taxes*:

1. En la pestaña **Countries**, agrega **Chile** con tasa por defecto **19 %**.
2. En la pestaña **Channels**, elige `b2b-cl`:
   - cobra impuestos (`chargeTaxes = true`);
   - calcula con tasas fijas (*Flat rates*, `taxCalculationStrategy = FLAT_RATES`);
   - toma los precios como **sin** impuesto (`pricesEnteredWithTax = false`);
   - los muestra sin impuesto (`displayGrossPrices = false`).
3. No toques `retail-cl`. Ahí los precios sí se ingresan con IVA incluido.

**Comprobación:** en un carrito de `b2b-cl`, el total es el subtotal neto × 1,19
más el envío, y la orden de prueba (§ h) muestra el IVA desglosado en el
dashboard.

**Tramos y precios negociados también van netos.** Con
`pricesEnteredWithTax = false`, el precio que ventu-b2b fija en una línea se
toma sin IVA y Saleor le suma el 19 %. ventu-b2b lee esta configuración del
canal, calcula el tramo sobre el neto y muestra la tabla en la base en que el
canal muestra sus precios (`displayGrossPrices`): neta en `b2b-cl`, igual que
el precio de lista de la ficha. El storefront muestra netos en todo canal B2B
(`B2B_CHANNELS`) y desglosa el IVA aparte en carrito, checkout y pedidos
(subtotal neto, IVA, total). Dos consecuencias para el staff:

- El `precio_unitario` de un carrito negociado (`POST /cart`) se ingresa
  **neto**.
- Una tabla de montos en `ventu.pricing.tramos` (`1=13240,4=8900`) se lee como
  neta. Si se copió de Ventu 1.0 con IVA incluido, divide cada monto por 1,19
  antes de abrir la compra; si no, cada tramo cobra un 19 % de más. Las
  escaleras en factores (`1:1.0,10:0.9`) no cambian.

---

## e. Correo de confirmación de cuenta

Saleor tiene activa la confirmación por correo
(`enableAccountConfirmationByEmail`) y no hay envío de correo configurado. Una
cuenta nueva nunca se confirma, y `tokenCreate` le responde
`ACCOUNT_NOT_CONFIRMED`. El cliente no puede iniciar sesión. Además, el signup
del storefront necesita ese `tokenCreate` para obtener el id del usuario nuevo
(Saleor 3.23 lo devuelve vacío en `accountRegister`), así que tampoco alcanza a
registrar la empresa.

Antes de abrir el registro, elige **una** de estas dos opciones:

- **Conectar el correo (preferido).** Configura SMTP en Saleor (*Configuration →
  Plugins → User emails*, o una app de correo) y define `DEFAULT_FROM_EMAIL`.
  Comprueba que `saleor-worker` esté corriendo: el correo lo envía el worker, no
  la API. Se prefiere porque así el correo de contacto de una empresa que va a
  comprar por pagar queda verificado.
- **No exigir la confirmación.** Desactiva la confirmación
  (`enableAccountConfirmationByEmail = false`) o permite iniciar sesión sin
  confirmar (`allowLoginWithoutConfirmation = true`). En ese caso, verificar el
  contacto pasa a ser parte de la aprobación (§ g): `/company/pendientes`
  informa `correo_confirmado`. Hace falta un token de staff con
  `MANAGE_SETTINGS`:

  ```bash
  curl -s "https://<dominio-de-la-api>/graphql/" \
    -H "Authorization: Bearer $SALEOR_STAFF_JWT" \
    -H "Content-Type: application/json" \
    -d '{"query":"mutation { shopSettingsUpdate(input: {allowLoginWithoutConfirmation: true}) { shop { enableAccountConfirmationByEmail allowLoginWithoutConfirmation } errors { field code message } } }"}'
  ```

**Comprobación:** crea una cuenta nueva y confirma que puede iniciar sesión.
Prueba también con una cuenta creada **antes** del cambio, que quedó sin
confirmar. Con SMTP, revisa además que el correo haya llegado.

---

## f. Celery beat y variables de negocio

### Celery beat no está corriendo

`saleor-worker` corre sin beat (sin `-B`) y no hay otro proceso beat. Las tareas
asíncronas, como webhooks y correos, sí se ejecutan porque las toma el worker.
Las **periódicas** de Saleor, en cambio, no corren nunca, y eso rompe varias
cosas:

- **Búsqueda.** Los productos nuevos o editados no se reindexan, así que la
  búsqueda del catálogo no los encuentra.
- **Promociones.** Los precios con descuento no se recalculan cuando una
  promoción empieza o termina.
- **Limpieza.** Los checkouts vencidos no se borran, las reservas de stock
  vencidas no se liberan y las órdenes sin confirmar no expiran.

La lista exacta es `CELERY_BEAT_SCHEDULE` en la versión de Saleor desplegada.

Para arreglarlo, levanta **un solo** proceso beat: con dos, cada tarea corre dos
veces. Puede ser un servicio aparte con la misma imagen de Saleor y el comando
`celery --app saleor.celeryconf:app beat --loglevel=info`, o `--beat` en el
comando del worker si este tiene una sola réplica. Para comprobarlo, busca en el
log `Scheduler: Sending due task`.

Al activarlo, Saleor empieza a borrar los checkouts inactivos según sus plazos,
incluidos los carritos de WhatsApp antiguos. Si alguno sigue vigente, revísalo
antes.

### Variables de negocio de ventu-b2b

| Variable | Por defecto | Qué pasa si queda así | Formato |
|---|---|---|---|
| `B2B_INSTRUCCIONES_TRANSFERENCIA` | vacío | `POST /pedido` devuelve `instrucciones_pago: null`. El cliente queda con un pedido por pagar sin saber a qué cuenta transferir. **Bloqueante.** | texto libre: banco, tipo y número de cuenta, RUT, correo para el comprobante |
| `PRICING_TIERS_B2B_CL` | vacío (usa `PRICING_TIERS`) | los productos sin tabla propia no tienen tramos. Es válido: la tabla del producto manda siempre | factores sobre el precio del canal (el neto en `b2b-cl`, § d): `1:1.0,10:0.9,50:0.8` |
| `B2B_MARKUP_MINIMO` | `0` | `POST /cart` no revisa el margen de los precios negociados | fracción de utilidad neta sobre costo: `0.25` = 25 % (se combina con `B2B_COMISION_PASARELA`, también fracción) |
| `B2B_STOCK_MINIMO_TRAMOS` | `0` | la tabla se publica con cualquier stock. Los tramos que el stock no cubre se descartan igual | entero: `10` |

> **`B2B_DEFAULT_NIVEL_PRECIO` debe quedar en `retail-cl`.** Una empresa está
> aprobada cuando su nivel es un canal de `B2B_CANALES`. Si el nivel por
> defecto fuera `b2b-cl`, toda empresa nacería aprobada y la revisión se
> saltaría sin que nada lo avise.

---

## g. Aprobar empresas

Una empresa recién registrada queda **en revisión**. Ve la tabla de tramos, pero
no puede comprar: `POST /pedido` le responde 403 con «Tu empresa está en
revisión. Te avisaremos cuando esté habilitada para comprar.». La aprueba el
staff, a mano.

**1. Listar las pendientes**, las más antiguas primero:

```bash
curl -s "$B2B_URL/company/pendientes" \
  -H "Authorization: Bearer $B2B_STAFF_TOKEN" | jq
```

```json
{
  "empresas": [
    {
      "user_id": "<user_id>",
      "email": "<correo>",
      "nombre": "<nombre y apellido>",
      "rut": "<rut>",
      "razon_social": "<razón social>",
      "giro": "<giro>",
      "telefono": "<teléfono>",
      "nivel_precio": "retail-cl",
      "cuenta_creada": "<fecha ISO>",
      "empresa_registrada": "<fecha ISO>",
      "correo_confirmado": true,
      "activa": true
    }
  ],
  "total": 1,
  "truncado": false
}
```

Si `truncado` es `true`, la respuesta trae además un `aviso`: hay más pendientes
de las que caben en una respuesta. Aprueba las que ves y vuelve a consultar.

**2. Revisar**, como mínimo:
- que el RUT y la razón social coincidan en el SII, con giro vigente;
- que el contacto sea real: `correo_confirmado`, o una llamada al teléfono si se
  eligió no exigir la confirmación en § e;
- que la cuenta esté `activa`.

**3. Aprobar:**

```bash
curl -s -X PATCH "$B2B_URL/company/<user_id>" \
  -H "Authorization: Bearer $B2B_STAFF_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"nivel_precio": "b2b-cl", "actor": "<tu-correo>"}' \
  | jq '{aprobada, estado, nivel_precio}'
```

Se espera `{"aprobada": true, "estado": "aprobada", "nivel_precio": "b2b-cl"}`.
El cambio queda en `ventu.b2b.company_log` con tu `actor`.

**4. Avisar al cliente.** La app no envía correos: el aviso es manual, por correo
o WhatsApp.

**Otros casos:**

- **Revertir una aprobación.** Envía `{"nivel_precio": "retail-cl", "actor": …}`.
  La empresa vuelve a revisión y a la lista.
- **Rechazar.** No existe un estado «rechazada»: una empresa que no se aprueba
  sigue en la lista. Por ahora, la decisión se registra fuera de la app.
- **Empresas registradas antes de este cambio.** No tienen `ventu.b2b.estado` y
  **no aparecen** en la lista. Las que ya están en `b2b-cl` siguen aprobadas, sin
  hacer nada. Para una que está en `retail-cl`, busca su `user_id` con
  `GET /company/por-rut/{rut}` y reenvía su nivel actual:

  ```bash
  curl -s -X PATCH "$B2B_URL/company/<user_id>" \
    -H "Authorization: Bearer $B2B_STAFF_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"nivel_precio": "retail-cl", "actor": "<tu-correo>"}'
  ```

  Eso solo escribe el estado que falta. No cambia condiciones ni agrega una
  entrada al historial, y desde ahí la empresa aparece en `/company/pendientes`.

---

## h. Prueba de humo

Hazla con una cuenta de prueba nueva, en ventana privada.

### B2B, de punta a punta

1. Abre `https://<dominio-del-storefront>/es/b2b-cl`. Sin sesión, redirige a
   `/login`. Crea la cuenta en `/es/b2b-cl/signup` con razón social y un RUT de
   prueba válido.
2. Inicia sesión (§ e). `/es/b2b-cl/empresa` muestra la empresa **en revisión**,
   y en el pago todos los medios aparecen deshabilitados. En la ficha de un
   producto con tramos, la tabla **sí** se ve.
3. Si intentas crear el pedido, el mensaje debe ser exactamente «Tu empresa está
   en revisión. Te avisaremos cuando esté habilitada para comprar.».
4. Como staff: la empresa aparece en `/company/pendientes`. Apruébala (§ g).
5. Recarga la página: ahora la transferencia está habilitada. Maxxa solo se
   habilita con crédito aprobado.
6. Agrega al carrito un producto con tramos, en una cantidad que alcance uno. El
   precio unitario neto del carrito debe ser el de la tabla de la ficha, y el
   resumen debe mostrar subtotal neto, IVA y total.
7. En el checkout, ingresa la dirección de despacho, elige el envío y paga con
   **Transferencia**. El pedido se crea y se muestran el número y las
   instrucciones de transferencia (§ f). El total debe ser el neto más el 19 %
   de IVA (§ d) más el envío.
8. En el dashboard, en *Orders*, busca la orden. Debe estar en `b2b-cl`, sin
   pago registrado y con esta metadata:
   - `ventu.pago.metodo = transferencia`
   - `ventu.pago.estado = pendiente`
   - `ventu.b2b.rut`
   - `ventu.b2b.razon_social`
9. Durante toda la prueba, el log de ventu-b2b no debe mostrar respuestas 401. Si
   aparecen, el token de servicio del storefront y el de ventu-b2b no coinciden
   (§ a).
10. Al terminar, cancela la orden de prueba en el dashboard.

### Retail

1. En ventana privada, abre `https://<dominio-del-storefront>/es/retail-cl`. El
   catálogo se ve sin iniciar sesión y los precios incluyen IVA.
2. La ficha no muestra tabla de tramos, ni en ventana privada ni con la sesión
   de un usuario que tiene empresa registrada.
3. El registro y el checkout no piden RUT, y el pago no muestra los medios B2B.
4. Mientras no haya pasarela real, el paso de pago de retail no ofrece ningún
   medio (§ c). Es lo esperado: no hay forma de cerrar una orden retail.
