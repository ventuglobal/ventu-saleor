# Ventu Correo

Envío de correos de todo el proyecto por [Resend](https://resend.com). Concentra
en un solo lugar la clave de Resend, el remitente y las plantillas, en vez de
repetirlos en cada app. Mismo contrato que `src/lib/email.ts` de
storefront-next: el envío nunca lanza y devuelve si salió y por qué no.

Paquete importable: `ventu_correo/` (la carpeta de deploy usa guion).

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/health` | qué está configurado (sin valores) |
| POST | `/enviar` | envía un correo; `Authorization: Bearer $CORREO_SERVICE_TOKEN` |
| GET | `/manifest` | manifest de Saleor App (`MANAGE_USERS` + webhooks de cuenta) |
| POST | `/register` | Saleor entrega su token al instalar (no se usa) |
| POST | `/webhooks/saleor` | correos de cuenta que pide Saleor, firma JWS verificada |

### Usarlo desde otro servicio

```bash
curl -s https://<dominio>/enviar \
  -H "Authorization: Bearer $CORREO_SERVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"para": "cliente@ejemplo.cl", "asunto": "Tu pedido #123",
       "html": "<p>…</p>", "texto": "…", "etiqueta": "pedido-b2b",
       "clave_idempotencia": "pedido-123",
       "adjuntos": [{"nombre": "cotizacion.pdf", "contenido_b64": "…", "tipo": "application/pdf"}]}'
```

En vez de `html` se puede mandar un `aviso`: solo el texto, y el servicio lo
arma con el mismo marco que los correos de cuenta (nombre de la tienda,
saludo, botón, enlace de respaldo y pie). Así los avisos de todos los servicios
se ven iguales sin repetir HTML.

```json
{"para": "cliente@ejemplo.cl", "asunto": "Tu empresa ya puede comprar en Ventu",
 "aviso": {"nombre": "Ana", "parrafos": ["…", "…"],
           "boton": {"texto": "Ir a la tienda", "url": "https://…/es/b2b-cl"},
           "pie": "…"},
 "etiqueta": "empresa-aprobada", "clave_idempotencia": "…"}
```

Respuesta `{"enviado": bool, "id": str|null, "error": str|null}`: 200 si salió,
503 si falta configurar el servicio, 502 si Resend lo rechazó. Quien reintenta
debe mandar la misma `clave_idempotencia` (Resend descarta el duplicado 24 h).

### Correos de cuenta (Saleor)

| Evento | Plantilla | Enlace |
|---|---|---|
| `ACCOUNT_CONFIRMATION_REQUESTED` | Confirma tu cuenta | `redirectUrl?email=…&token=…` |
| `ACCOUNT_SET_PASSWORD_REQUESTED` | Crea tu contraseña | `redirectUrl?email=…&token=…` |

El `redirectUrl` lo pone el storefront y Saleor lo valida contra
`ALLOWED_CLIENT_HOSTS`. Las firmas se verifican con el JWKS de
`SALEOR_API_URL`: un webhook de otra instancia de Saleor no pasa. Si el envío
falla se responde 503 y Saleor reintenta; la clave de idempotencia sale del
token, así que un reintento no duplica el correo.

## Config (env)

```
RESEND_API_KEY=...            # secreto; sin él no se envía nada
MAIL_FROM=Ventu <cuentas@send.clickbox.cl>   # dominio verificado en Resend
MAIL_REPLY_TO=                # opcional
SALEOR_API_URL=https://<saleor-api>/graphql/
CORREO_SERVICE_TOKEN=...      # para /enviar; vacío = /enviar cerrado (503)
CORREO_AUTH_ABIERTA=1         # solo local: /enviar sin token
CORREO_NOMBRE_TIENDA=Ventu    # encabezado de los avisos (por omisión, Ventu)
```

Instalación y comprobación: `docs/b2b/lanzamiento.md` § e.

> Local: `pip install -r requirements.txt && PYTHONPATH=. uvicorn ventu_correo.main:app --port 8095`
> Tests: `pytest` (no salen a la red: Resend y el JWKS se simulan).
