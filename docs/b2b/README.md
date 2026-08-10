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

La App B2B hace tres cosas y ninguna más:

1. **Identificar** una empresa por su RUT
2. **Asociarla** al usuario y a sus órdenes
3. **Canalizar** su solicitud de crédito hacia Maxxa

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

### 2. Cotización

Se implementa sobre **draft orders de Saleor**. No requiere entidad nueva:

| Necesidad | Mecanismo Saleor |
|---|---|
| Crear cotización | `draftOrderCreate` (con `metadata`, `user`, `channelId`) |
| Ajustar precio negociado | `orderLineDiscountUpdate`, `orderDiscountAdd` |
| Observaciones | `customerNote`, `orderNoteAdd` |
| Convertir en pedido | `draftOrderComplete` |

Flujo: la empresa arma el carro → solicita cotización → se crea la draft order
con la metadata de la empresa → Ventu ajusta y la envía → la empresa la acepta y
se convierte en orden.

### 3. Solicitud de crédito

Paso **voluntario y adicional**. No es requisito para crear cuenta ni para
comprar al contado.

```
"Solicitar crédito" → Ventu registra estado = pendiente
                    → deriva al cliente a Maxxa
                    → Maxxa recibe la Carpeta Tributaria y evalúa
                    → Ventu recibe solo el resultado
```

**Regla de diseño crítica: la Carpeta Tributaria la recibe Maxxa, no Ventu.**

La derivación debe ser una **redirección** hacia Maxxa, no una carga de archivo
en Ventu que luego se reenvíe. La diferencia es sustantiva: si el documento pasa
por la infraestructura de Ventu —aunque sea de forma transitoria— Ventu queda en
la ruta del dato y hereda las obligaciones de custodia, retención y control de
acceso sobre el historial tributario completo del cliente.

Derivando, Ventu solo almacena `credito_estado` y `maxxa_ref`. Esto elimina el
mayor riesgo de cumplimiento del MVP, en particular frente a la Ley 21.719 de
protección de datos personales.

### 4. Compra

Sin cambios respecto del flujo actual, salvo la metadata de empresa en el
checkout y el canal correspondiente a su `nivel_precio`.

## Precios en 1.0

**Precio plano por canal.** Un único nivel mayorista, sin tramos por cantidad.

Pricing ya opera así: `compute_channel_prices(cost_net)` calcula un precio por
canal y lo escribe en Saleor. La empresa compra en el canal indicado por su
`nivel_precio`.

El precio por empresa y los tramos por cantidad quedan registrados en el roadmap.

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
- Tramos de precio por cantidad
- Precio negociado por empresa

## Dependencias

| Dependencia | Estado |
|---|---|
| Canal B2B en Saleor | ❌ No existe. Figura en `scripts/provision.py` pero nunca se creó |
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
- Tramos por cantidad (*volume pricing*): 1-9 / 10-49 / 50+
- Reglas de cantidad: mínimos de compra, múltiplos, venta por caja
- Vigencia de precios acordados

> Saleor no soporta precios escalonados por cantidad de forma nativa. Requiere
> diseño específico. La decisión pendiente es si los tramos son por cantidad de
> línea o por monto total del pedido: determina por completo la solución.

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
