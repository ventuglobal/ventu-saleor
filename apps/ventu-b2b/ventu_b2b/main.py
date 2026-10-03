"""App B2B de Ventu.

Aporta identidad empresarial y continuidad comercial sobre Saleor:

- identifica una empresa por su RUT y la asocia al usuario
- convierte una conversación de WhatsApp en un carrito recuperable por enlace
- cuelga la identidad tributaria del checkout para que llegue a la orden

Es su propia Saleor App porque necesita `MANAGE_USERS` (escribir la metadata del
cliente) y `HANDLE_CHECKOUTS` (fijar el precio de una línea), permisos que las
demás apps de Ventu no tienen ni necesitan.

**Acceso.** Toda ruta que toca datos exige un token Bearer (ver `config`): el de
servicio lo envía el servidor del storefront, el de staff las herramientas
internas. `user_id` sigue llegando en el cuerpo, así que el token de servicio
equivale a «confío en que el storefront ya autenticó a este usuario».

**Handlers síncronos.** El cliente de Saleor es bloqueante (httpx sync). Con
`def` FastAPI corre cada handler en su threadpool; con `async def` una consulta
lenta congelaría el event loop y con él a todas las demás, incluido `/health`.
"""

from __future__ import annotations

import hmac
import logging
import sys
from typing import List, Optional, Sequence

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import auditoria, avisos, config
from .cart import link as link_mod
from .cart import precios as precios_mod
from .cart import reprecio as reprecio_mod
from .cart import service as cart
from .company import rut as rut_mod
from .company import service as company_svc
from .credito import estados as credito_st
from .credito import service as credito_svc
from .pedido import medios as medios_mod
from .pedido import service as pedido_svc
from .company import models as company_models
from .company.models import CONDICIONES_PAGO, Company, CompanyInvalida
from .saleor_client import SaleorError, SaleorTimeoutError
from .tiers import TramoInvalido

# A stdout: Railway marca como error todo lo que sale por stderr, y así un
# INFO de rutina tapaba los errores de verdad.
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
# httpx registra cada petición a Saleor en INFO: ruido, y con la URL completa.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("ventu-b2b")

# Cliente de Maxxa. `None` mientras no esté configurado: el endpoint de carpeta
# responde 503 en vez de aceptar documentos que no puede entregar.
maxxa = None

app = FastAPI(title="Ventu B2B", version="0.1.0")


# ─────────────────────────── acceso ───────────────────────────

def _algun_token() -> bool:
    return bool(config.SERVICE_TOKEN or config.STAFF_TOKEN)


def _api_abierta() -> bool:
    """Abierta solo si se pidió explícitamente y no hay ningún token."""
    return config.AUTH_ABIERTA and not _algun_token()


def _exigir(authorization: str, aceptados: Sequence[str]) -> None:
    """Deja pasar si el Bearer coincide con alguno de los tokens aceptados.

    Con al menos un token configurado, una ruta cuyos tokens aceptados están
    todos vacíos queda **cerrada**: configurar solo el de servicio no debe
    dejar abiertas por omisión las rutas de staff.

    Sin ningún token la API también queda cerrada (503), salvo que se haya
    pedido abrirla con B2B_AUTH_ABIERTA=1. Antes quedaba abierta y la única
    defensa era una línea en el log: bastaba un entorno nuevo sin las
    variables para dejar la aprobación de empresas y los precios negociados a
    disposición de cualquiera.
    """
    if not _algun_token():
        if config.AUTH_ABIERTA:
            return  # abierto a pedido (solo dev; se avisa al arrancar)
        raise HTTPException(status_code=503,
                            detail="la API no tiene credenciales configuradas")
    presentado = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    valido = False
    for esperado in aceptados:
        # Se comparan bytes: `compare_digest` con str rechaza lo que no es ASCII
        # y respondería 500 a un header mal formado.
        if presentado and esperado and hmac.compare_digest(presentado.encode(),
                                                           esperado.encode()):
            valido = True
    if not valido:
        raise HTTPException(status_code=401, detail="token de acceso inválido o ausente",
                            headers={"WWW-Authenticate": "Bearer"})


def _requiere_servicio(authorization: str = Header(default="")) -> None:
    """Rutas del cliente: las llama el storefront. El staff también puede."""
    _exigir(authorization, (config.SERVICE_TOKEN, config.STAFF_TOKEN))


def _requiere_staff(authorization: str = Header(default="")) -> None:
    """Rutas internas: fijan condiciones comerciales. El token del storefront
    no alcanza, para que filtrarlo no permita aprobarse crédito a uno mismo."""
    _exigir(authorization, (config.STAFF_TOKEN,))


SERVICIO = [Depends(_requiere_servicio)]
STAFF = [Depends(_requiere_staff)]


def _avisar_si_abierto() -> None:
    if _api_abierta():
        logger.warning("(b2b) B2B_AUTH_ABIERTA=1 y sin tokens: la API queda "
                       "ABIERTA a cualquiera. Solo aceptable en desarrollo local.")
    elif not _algun_token():
        logger.error("(b2b) B2B_SERVICE_TOKEN y B2B_STAFF_TOKEN vacíos: toda "
                     "ruta con datos responde 503 hasta configurarlos.")
    elif not config.STAFF_TOKEN:
        logger.warning("(b2b) B2B_STAFF_TOKEN vacío: las rutas de staff "
                       "responden 401 a todo.")


_avisar_si_abierto()


# Con la API protegida, el esquema publicado sería un mapa de lo que hay que
# atacar: solo se publica con la API abierta a pedido (desarrollo). Se decide
# por petición y no al construir la app para que el comportamiento siga a la
# configuración vigente.
_RUTAS_DOCS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


class _SinDocsConToken:
    def __init__(self, asgi) -> None:
        self.asgi = asgi

    async def __call__(self, scope, receive, send) -> None:
        if (scope["type"] == "http" and scope.get("path") in _RUTAS_DOCS
                and not _api_abierta()):
            await JSONResponse({"detail": "Not Found"}, status_code=404)(
                scope, receive, send)
            return
        await self.asgi(scope, receive, send)


app.add_middleware(_SinDocsConToken)


# ─────────────────────────── errores con código ───────────────────────────

class ErrorConCodigo(Exception):
    """Rechazo de negocio con un código estable además del mensaje.

    Responde `{"detail": <castellano>, "code": <CÓDIGO>}`. El mensaje es para
    mostrarlo tal cual; el código, para que el storefront decida qué hacer sin
    depender de un texto que puede cambiar de redacción.
    """

    def __init__(self, status: int, detail: str, code: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code


@app.exception_handler(ErrorConCodigo)
async def _error_con_codigo(request: Request, exc: ErrorConCodigo) -> JSONResponse:
    return JSONResponse(status_code=exc.status,
                        content={"detail": exc.detail, "code": exc.code})


# Mensaje exacto que ve una empresa en revisión al intentar comprar. El
# storefront lo muestra tal cual.
EN_REVISION = ("Tu empresa está en revisión. Te avisaremos cuando esté "
               "habilitada para comprar.")


# ─────────────────────────── errores de Saleor ───────────────────────────

def _ruta(request: Request) -> str:
    # La plantilla y no la URL: la URL lleva user_id o RUT, que no van al log.
    ruta = request.scope.get("route")
    return getattr(ruta, "path", "") or "?"


@app.exception_handler(SaleorTimeoutError)
async def _saleor_sin_respuesta(request: Request, exc: SaleorTimeoutError) -> JSONResponse:
    logger.error("(b2b) Saleor sin respuesta en %s %s: %s",
                 request.method, _ruta(request), exc)
    return JSONResponse(status_code=504, content={
        "detail": "Saleor no respondió a tiempo; intenta de nuevo en unos segundos"})


@app.exception_handler(SaleorError)
async def _saleor_fallo(request: Request, exc: SaleorError) -> JSONResponse:
    # El detalle queda en el log y no en la respuesta: puede traer nombres de
    # permisos o del esquema que no le sirven al cliente.
    logger.error("(b2b) fallo de Saleor en %s %s: %s",
                 request.method, _ruta(request), exc)
    return JSONResponse(status_code=502, content={
        "detail": "no se pudo completar la operación con Saleor; intenta de nuevo"})


# ─────────────────────────── infra ───────────────────────────

_HOSTS_LOCALES = {"localhost", "127.0.0.1", "[::1]"}


def _base_publica(request: Request) -> str:
    """URL con que Saleor debe llamar a la app.

    Detrás del proxy de Railway el proceso recibe http, y `request.base_url`
    anunciaba `http://…`: Saleor no instala una app así. Manda
    `B2B_PUBLIC_URL`; si no está, lo que dice el proxy; si no hay proxy, https
    salvo en local.

    Los encabezados se leen aquí a propósito y no a través de
    `--proxy-headers` de uvicorn (que el Dockerfile activa): si Railway arranca
    el servicio con otro comando, o uvicorn no confía en la IP del proxy, el
    resultado es el mismo. Y uvicorn no reescribe el host con
    `X-Forwarded-Host`, así que igual habría que leerlo a mano.
    """
    if config.PUBLIC_URL:
        return config.PUBLIC_URL
    encabezados = request.headers
    host = ((encabezados.get("x-forwarded-host") or "").split(",")[0].strip()
            or encabezados.get("host") or request.url.netloc)
    proto = (encabezados.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if proto not in ("http", "https"):
        nombre = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        proto = "http" if nombre in _HOSTS_LOCALES else "https"
    return f"{proto}://{host}"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/manifest")
async def manifest(request: Request) -> dict:
    base = _base_publica(request)
    return {
        "id": "cl.ventu.b2b",
        "version": "0.1.0",
        "name": "Ventu B2B",
        "about": "Identidad empresarial y carritos de WhatsApp sobre Saleor.",
        # IMPERSONATE_USER: `checkoutCustomerAttach` lo exige a una app que
        # asocia un carrito a un cliente distinto de sí misma (carritos de
        # WhatsApp armados para un cliente identificado).
        "permissions": ["MANAGE_USERS", "HANDLE_CHECKOUTS", "MANAGE_CHECKOUTS",
                        "IMPERSONATE_USER"],
        "appUrl": base,
        "tokenTargetUrl": f"{base}/register",
        "webhooks": [],
    }


@app.post("/register")
async def register(request: Request) -> dict:
    """Recibe el token de instalación de Saleor.

    Hoy no se guarda: la app opera con `SALEOR_AUTH_TOKEN` fijado a mano. El
    token nunca va al log, ni siquiera su largo.
    """
    body = await request.json()
    token = body.get("auth_token")
    if not token:
        raise HTTPException(400, "falta auth_token")
    logger.info("(b2b) app registrada en Saleor (token no persistido)")
    return {"status": "ok"}


# ─────────────────────────── empresas ───────────────────────────

class CompanyIn(BaseModel):
    user_id: str
    rut: str
    razon_social: str
    giro: str = ""
    telefono: str = ""
    # `nivel_precio` ya no se acepta: si lo eligiera quien se registra,
    # cualquiera se asignaría precio mayorista. Lo fija el staff (PATCH).


def _vista_empresa(company: Company) -> dict:
    # `aprobada` sale del nivel, no del espejo público: así una empresa anterior
    # al espejo se sigue leyendo bien (ver `company.models.esta_aprobada`).
    aprobada = company_models.esta_aprobada(company)
    return {
        "registrada": True,
        "rut": company.rut,
        "razon_social": company.razon_social,
        "nivel_precio": company.nivel_precio,
        "condicion_pago": company.condicion_pago,
        "credito_estado": company.credito_estado,
        "aprobada": aprobada,
        "estado": company_models.estado_de(company),
        "medios_pago": medios_mod.disponibles(
            tiene_credito=company_models.tiene_credito(company),
            aprobada=aprobada),
    }


@app.post("/company", dependencies=SERVICIO)
def registrar_empresa(entrada: CompanyIn) -> dict:
    """Da de alta la empresa y la asocia al usuario."""
    try:
        company = Company(
            rut=entrada.rut,
            razon_social=entrada.razon_social,
            giro=entrada.giro,
            telefono=entrada.telefono,
            nivel_precio=config.DEFAULT_NIVEL_PRECIO,
        )
    except (rut_mod.RutInvalido, CompanyInvalida) as exc:
        # 422: el dato es inválido, no es un fallo del servidor.
        raise HTTPException(422, str(exc)) from exc

    if company_svc.obtener_de_usuario(entrada.user_id):
        # Re-registrar reescribiría las condiciones comerciales con los valores
        # iniciales: borraría el nivel asignado y el crédito aprobado.
        raise HTTPException(409, "el usuario ya tiene una empresa registrada; "
                                 "los cambios los hace el equipo de Ventu")

    try:
        company_svc.registrar(entrada.user_id, company)
    except company_svc.EmpresaYaRegistrada as exc:
        # 409 y no 400: el conflicto es con el estado actual, no con la petición.
        # Es el caso del colega de la misma empresa y merece respuesta propia.
        raise HTTPException(409, str(exc)) from exc

    # Una empresa recién dada de alta queda en revisión (salvo que el nivel por
    # defecto sea B2B): el storefront lo dice de entrada, sin otra consulta.
    return {"status": "ok", "rut": company.rut,
            "nivel_precio": company.nivel_precio,
            "aprobada": company_models.esta_aprobada(company),
            "estado": company_models.estado_de(company)}


@app.get("/company/de-usuario/{user_id}", dependencies=SERVICIO)
def empresa_de_usuario(user_id: str) -> dict:
    """¿Este usuario compra como empresa?

    Es la pregunta que hace el storefront en cada carga del catálogo B2B, así
    que responde 200 siempre: un usuario sin empresa no es un error, es el
    estado normal de quien recién se registró.
    """
    company = company_svc.obtener_de_usuario(user_id)
    if not company:
        return {"registrada": False}
    return _vista_empresa(company)


class CompanyPatch(BaseModel):
    nivel_precio: Optional[str] = None
    condicion_pago: Optional[str] = None
    razon_social: Optional[str] = None
    giro: Optional[str] = None
    telefono: Optional[str] = None
    # Quién hizo el cambio, para el historial. Lo declara la herramienta
    # interna: el token de staff es compartido y no identifica a nadie.
    actor: Optional[str] = None


@app.patch("/company/{user_id}", dependencies=STAFF)
def actualizar_empresa(user_id: str, entrada: CompanyPatch) -> dict:
    """Cambia condiciones comerciales o datos de la empresa (solo staff).

    Es la vía para **aprobar** una empresa revisada: pasarla a un nivel de
    `B2B_CANALES` la habilita para comprar, y devolverla a uno que no lo es la
    deja otra vez en revisión. El alta la deja siempre en el nivel por defecto.

    Al aprobarla se avisa al cliente por correo; `aviso_cliente` en la
    respuesta dice si salió. Que no salga no deshace la aprobación.
    """
    cambios = {campo: valor for campo, valor in entrada.model_dump().items()
               if campo != "actor" and valor is not None}
    if not cambios:
        raise HTTPException(422, "no hay cambios que aplicar")
    if "nivel_precio" in cambios and cambios["nivel_precio"] not in config.NIVELES_PERMITIDOS:
        # Lista cerrada: un canal mal escrito dejaría a la empresa sin precio
        # en ningún producto.
        raise HTTPException(422, f"nivel de precio no permitido: {cambios['nivel_precio']!r}; "
                                 f"opciones: {', '.join(config.NIVELES_PERMITIDOS)}")
    if "condicion_pago" in cambios and cambios["condicion_pago"] not in CONDICIONES_PAGO:
        raise HTTPException(422, f"condición de pago desconocida: {cambios['condicion_pago']!r}; "
                                 f"opciones: {', '.join(CONDICIONES_PAGO)}")

    ahora = auditoria.ahora_utc()
    try:
        res = company_svc.actualizar(user_id, cambios,
                                     actor=(entrada.actor or "staff").strip() or "staff",
                                     ahora=ahora)
    except CompanyInvalida as exc:
        raise HTTPException(422, str(exc)) from exc
    if res is None:
        raise HTTPException(404, "el usuario no tiene empresa asociada")
    vista = _vista_empresa(res.company)
    if res.recien_aprobada:
        # Después de escribir: solo se avisa lo que ya quedó guardado.
        vista["aviso_cliente"] = avisos.empresa_aprobada(user_id, res.email, res.nombre,
                                                         res.company, ahora)
    return vista


@app.get("/company/pendientes", dependencies=STAFF)
def empresas_pendientes() -> dict:
    """Empresas que esperan aprobación, las más antiguas primero (solo staff).

    Lista a partir del espejo público `ventu.b2b.estado`. Una empresa dada de
    alta antes de que existiera **no aparece**: se repara con un PATCH que
    reenvíe su nivel actual. Aprobar es `PATCH /company/{user_id}` con un nivel
    de `B2B_CANALES`.
    """
    empresas, truncado = company_svc.pendientes()
    respuesta = {"empresas": empresas, "total": len(empresas), "truncado": truncado}
    if truncado:
        # Que nadie tome la lista por completa: aprobar las que se ven y volver
        # a consultar trae las siguientes.
        respuesta["aviso"] = (f"se muestran las {len(empresas)} más antiguas; hay más "
                              "pendientes. Aprueba estas y vuelve a consultar.")
    return respuesta


@app.get("/company/por-rut/{rut_libre}", dependencies=STAFF)
def buscar_empresa(rut_libre: str) -> dict:
    """¿Este RUT ya está registrado? Normaliza antes de buscar.

    Solo staff: vincula un RUT con su `user_id`, y abierto permitiría recorrer
    empresas por RUT.
    """
    try:
        encontrado = company_svc.buscar_por_rut(rut_libre)
    except rut_mod.RutInvalido as exc:
        raise HTTPException(422, str(exc)) from exc

    if not encontrado:
        return {"registrada": False}
    user_id, company = encontrado
    return {"registrada": True, "user_id": user_id,
            "razon_social": company.razon_social}


# ─────────────────────────── crédito ───────────────────────────

class CreditoIn(BaseModel):
    user_id: str
    # Se acepta por compatibilidad y se ignora: la hora del registro la fija el
    # servidor, para que nadie pueda fechar una solicitud cuando le convenga.
    ahora: Optional[str] = None


@app.post("/credito/solicitar", dependencies=SERVICIO)
def solicitar_credito(entrada: CreditoIn) -> dict:
    """Abre una solicitud. Paso voluntario: no bloquea la compra al contado."""
    company = company_svc.obtener_de_usuario(entrada.user_id)
    if not company:
        raise HTTPException(404, "el usuario no tiene empresa asociada")
    try:
        s = credito_svc.solicitar(entrada.user_id, company, ahora=auditoria.ahora_utc())
    except credito_st.TransicionInvalida as exc:
        # 409: el conflicto es con el estado actual (p. ej. ya hay una solicitud
        # en curso), no con la petición.
        raise HTTPException(409, str(exc)) from exc
    except credito_svc.RegistroFallido as exc:
        logger.error("(b2b) no se pudo registrar la solicitud de crédito: %s", exc)
        raise HTTPException(502, "no se pudo registrar la solicitud; intenta de nuevo") from exc
    return {"estado": s.estado, "rut": s.company_rut}


class VeredictoIn(BaseModel):
    user_id: str
    veredicto: str
    referencia: str = ""
    # Ignorado, igual que en la solicitud: la hora la pone el servidor.
    ahora: Optional[str] = None
    actor: Optional[str] = None


@app.post("/credito/resolver", dependencies=STAFF)
def resolver_credito(entrada: VeredictoIn) -> dict:
    """Registra el resultado devuelto por Maxxa (solo staff)."""
    company = company_svc.obtener_de_usuario(entrada.user_id)
    if not company:
        raise HTTPException(404, "el usuario no tiene empresa asociada")
    try:
        s = credito_svc.resolver(entrada.user_id, company, entrada.veredicto,
                                 ahora=auditoria.ahora_utc(),
                                 referencia=entrada.referencia,
                                 actor=(entrada.actor or "staff").strip() or "staff")
    except credito_st.TransicionInvalida as exc:
        raise HTTPException(409, str(exc)) from exc
    except credito_svc.RegistroFallido as exc:
        logger.error("(b2b) no se pudo registrar el veredicto de crédito: %s", exc)
        raise HTTPException(502, "no se pudo registrar el veredicto; intenta de nuevo") from exc
    return {"estado": s.estado, "referencia": s.referencia}


@app.post("/credito/carpeta", dependencies=SERVICIO)
def recibir_carpeta(
    user_id: str = Form(...),
    ahora: Optional[str] = Form(None),
    archivo: UploadFile = File(...),
) -> dict:
    """Recibe la Carpeta Tributaria y la reenvía a Maxxa.

    Ventu queda en la ruta del dato, así que la ventana de exposición se acota
    al máximo: el documento no se persiste en este proceso —se entrega y se
    descarta— y solo se guardan el estado y la referencia.

    Mientras no exista el cliente real de Maxxa, el endpoint responde 503 en vez
    de aceptar el documento: recibir un historial tributario que no se puede
    entregar sería custodiarlo sin propósito.
    """
    company = company_svc.obtener_de_usuario(user_id)
    if not company:
        raise HTTPException(404, "el usuario no tiene empresa asociada")

    if company.credito_estado != credito_st.PENDIENTE:
        # Sin solicitud abierta no hay nada que evaluar, y aceptar el documento
        # significaría custodiarlo sin motivo.
        raise HTTPException(409, "no hay una solicitud de crédito en curso")

    if maxxa is None:
        raise HTTPException(503, "la integración con Maxxa no está configurada")

    # Se lee un byte más que el tope, no el archivo entero: basta para saber si
    # lo excede sin cargar en memoria lo que venga.
    contenido = archivo.file.read(config.CARPETA_MAX_BYTES + 1)
    if len(contenido) > config.CARPETA_MAX_BYTES:
        raise HTTPException(413, "la carpeta excede el tamaño permitido")

    try:
        referencia = credito_svc.entregar_carpeta(
            company, contenido, enviar_a_maxxa=maxxa.enviar_carpeta)
    except credito_svc.EntregaFallida as exc:
        # 502: el fallo es del tercero, no de quien subió el documento. Se
        # distingue para que el cliente sepa que puede reintentar sin cambiar
        # nada.
        raise HTTPException(502, str(exc)) from exc
    except credito_svc.CreditoError as exc:
        raise HTTPException(422, str(exc)) from exc

    return {"estado": credito_st.PENDIENTE, "referencia": referencia}


# ─────────────────────────── tramos visibles ───────────────────────────

@app.get("/tramos/{variant_id}", dependencies=SERVICIO)
def tramos_visibles(variant_id: str, user_id: str = "", canal: str = "") -> dict:
    """Tabla de tramos que corresponde mostrar a **este** usuario.

    La tabla es información comercial reservada: revela la política de descuentos
    por volumen y, con ella, el margen. Solo se entrega a un usuario con empresa
    registrada.

    Por eso vive en `privateMetadata` y no en `metadata`: la metadata de producto
    se lee sin autenticación, así que publicarla ahí la habría dejado a la vista
    de cualquiera —cliente retail o competidor— por mucho que el storefront no la
    dibujara. Ocultarla en la interfaz no es ocultarla.

    Un usuario sin empresa recibe `visible: false` y ninguna cifra. No se
    responde 403 a propósito: que un retail sepa que *existe* una tabla que no
    puede ver no aporta nada y sí invita a buscarla.

    `canal` es el del carrito o la vitrina que se está mirando: la tabla tiene
    que coincidir con lo que después cobra el reprecio, que usa el canal del
    carrito. En un canal que no es B2B no hay tabla.
    """
    if not user_id:
        return {"visible": False, "motivo": "sin_identificar"}

    company = company_svc.obtener_de_usuario(user_id)
    if not company:
        return {"visible": False, "motivo": "sin_empresa"}

    destino = canal or company.nivel_precio or config.CANAL_CARRITO
    if destino not in config.CANALES:
        # Fuera de un canal B2B el carrito cobra precio de lista (el reprecio
        # no corre ahí), así que mostrar la tabla sería prometer un precio que
        # no se cobra. Misma regla que CANAL_NO_B2B en /pedido.
        return {"visible": False, "motivo": "canal_no_b2b"}
    try:
        tabla = precios_mod.tabla_visible(
            variant_id, canal=destino,
            escalera_channel=config.tramos_del_canal(destino),
            stock_minimo=config.STOCK_MINIMO_TRAMOS)
    except Exception as exc:  # noqa: BLE001
        # La tabla es informativa: si no se puede leer, la ficha se muestra
        # igual y sin ella. El precio que se cobra lo decide el reprecio.
        logger.warning("(b2b) no se pudo leer la tabla de %s: %s", variant_id, exc)
        return {"visible": False, "motivo": "no_disponible"}

    if not tabla:
        # Sin tramos aplicables —el producto no tiene, o el stock no alcanza—.
        return {"visible": False, "motivo": "sin_tramos"}

    return {"visible": True, "rut": company.rut, "canal": destino,
            "tramos": tabla}


# ─────────────────────────── carritos ───────────────────────────

class LineaIn(BaseModel):
    variant_id: str
    cantidad: int = Field(gt=0)
    precio_unitario: Optional[float] = None


class CarritoIn(BaseModel):
    lineas: List[LineaIn]
    canal: Optional[str] = None
    origen: str = "whatsapp"
    user_id: Optional[str] = None
    # Confirma un precio negociado bajo el margen mínimo. Existe para que
    # vender bajo el piso sea una decisión explícita y no un descuido.
    forzar: bool = False


@app.post("/cart", dependencies=STAFF)
def crear_carrito(entrada: CarritoIn) -> dict:
    """Arma el carrito y devuelve el enlace para enviar por WhatsApp.

    Solo staff: admite precios fijados a mano, que el cliente no puede elegir.
    """
    if not entrada.lineas:
        raise HTTPException(422, "un carrito sin líneas no es una propuesta")

    extra = {}
    if entrada.user_id:
        company = company_svc.obtener_de_usuario(entrada.user_id)
        if company:
            # La identidad tributaria viaja con el carrito para llegar a la
            # orden: es lo que después permite facturar.
            extra = company.para_orden(company_id=entrada.user_id)

    # Si el llamador no fija precio, se resuelve por la cantidad: es el
    # comportamiento del sitio actual, donde la tabla de tramos vive en el
    # producto y la cantidad elegida determina el precio unitario.
    canal = entrada.canal or config.CANAL_CARRITO
    lineas: List[cart.Linea] = []
    # Líneas cuyo precio negociado queda bajo el margen mínimo.
    avisos: List[dict] = []
    for l in entrada.lineas:
        precio = l.precio_unitario
        if precio is None:
            try:
                precio = precios_mod.resolver_precio(
                    l.variant_id, l.cantidad, canal=canal,
                    escalera_channel=config.tramos_del_canal(canal))
            except TramoInvalido as exc:
                # Una escalera mal escrita no debe impedir vender: se cae al
                # precio de catálogo y queda el registro para corregirla.
                logger.warning("(b2b) tramos ilegibles para %s: %s", l.variant_id, exc)
                precio = None
            # Marcado como tramo: el reprecio podrá recalcularlo si cambia la
            # cantidad, cosa que con un precio negociado no debe hacer.
            lineas.append(cart.Linea(l.variant_id, l.cantidad, precio,
                                     motivo=cart.MOTIVO_TRAMO))
            continue

        # Precio fijado a mano por el ejecutivo: se revisa contra el margen
        # mínimo (`B2B_MARKUP_MINIMO`; sin él no hay revisión).
        bajo = precios_mod.revisar_negociado(
            l.variant_id, precio, canal=canal,
            markup_minimo=config.MARKUP_MINIMO,
            comision_pct=config.COMISION_PASARELA)
        if bajo:
            avisos.append({"variant_id": l.variant_id, **bajo})
        # El motivo negociado se fija explícito y no por omisión de `Linea`: es
        # la marca que impide que el reprecio recalcule lo que se acordó.
        lineas.append(cart.Linea(l.variant_id, l.cantidad, precio,
                                 motivo=cart.MOTIVO_NEGOCIADO))

    if avisos and not entrada.forzar:
        # Bajo el margen se rechaza salvo confirmación: una venta ajustada puede
        # ser legítima, pero no debe ocurrir sin que alguien lo decida.
        raise HTTPException(422, {
            "mensaje": "hay precios bajo el margen mínimo; reenvía con "
                       "\"forzar\": true para confirmarlos",
            "avisos_margen": avisos,
        })
    if avisos:
        logger.warning("(b2b) carrito con precios bajo el margen, forzado: %s", avisos)

    try:
        carrito = cart.crear(
            lineas,
            canal=entrada.canal or "",
            origen=entrada.origen,
            extra_metadata=extra,
        )
    except cart.CarritoError as exc:
        raise HTTPException(422, str(exc)) from exc

    respuesta = {"link_id": carrito.link_id, "url": carrito.url(),
                 "checkout_id": carrito.checkout_id}
    if avisos:
        respuesta["avisos_margen"] = avisos

    if entrada.user_id:
        try:
            cart.adjuntar_cliente(carrito.checkout_id, entrada.user_id)
        except (cart.CarritoError, SaleorError) as exc:
            # El carrito ya existe: fallar aquí perdería el enlace y dejaría un
            # checkout huérfano. El cliente puede asociarlo al abrir el enlace
            # con su sesión iniciada.
            logger.warning("(b2b) carrito %s creado sin asociar al cliente: %s",
                           carrito.checkout_id, exc)
            respuesta["aviso"] = ("el carrito se creó pero no quedó asociado al "
                                  "cliente; se asociará cuando lo abra con su sesión")
    return respuesta


@app.get("/cart/{link_id}", dependencies=SERVICIO)
def resolver_carrito(link_id: str) -> dict:
    """Resuelve el enlace hacia el carrito vigente."""
    if not link_mod.es_valido(link_id):
        raise HTTPException(404, "enlace no encontrado")

    try:
        nodo = cart.resolver(link_id)
    except cart.CarritoError as exc:
        logger.error("(b2b) no se pudo resolver el enlace: %s", exc)
        raise HTTPException(502, "no se pudo recuperar el carrito; intenta de nuevo") from exc
    if not nodo:
        # 410 y no 404: el enlace fue válido y ya no lo es. Permite al
        # storefront ofrecer rehacer el carrito en vez de mostrar "no existe".
        raise HTTPException(410, "el carrito ya no está disponible")

    return {"checkout_id": nodo["id"], "token": nodo.get("token"),
            "canal": (nodo.get("channel") or {}).get("slug")}


def _checkout_del_usuario(checkout_id: str, user_id: str) -> dict:
    """Lee el carrito y verifica que sea de este usuario.

    Sin esto, quien conozca un `checkout_id` ajeno podría reprecificarlo o
    cerrarlo como pedido a nombre de otra empresa.
    """
    checkout = reprecio_mod.leer_checkout(checkout_id)
    if not checkout:
        raise HTTPException(404, "el carrito no existe")
    dueno = (checkout.get("user") or {}).get("id")
    if not dueno or dueno != user_id:
        raise HTTPException(403, "el carrito no pertenece a este usuario")
    return checkout


class ReprecioIn(BaseModel):
    checkout_id: str
    user_id: str


@app.post("/cart/reprecio", dependencies=SERVICIO)
def reprecificar(entrada: ReprecioIn) -> dict:
    """Aplica al carrito el precio por volumen que corresponde a cada cantidad.

    Solo para empresas registradas: los tramos son su precio, no el de cualquiera
    que tenga el enlace del canal. Un usuario sin empresa recibe `aplicado:
    false` y el carrito queda con el precio de catálogo, que es lo correcto.

    Un fallo responde error y no `aplicado: false`: el storefront tiene que
    saber que el total que muestra puede no ser el que se cobrará. El pedido
    reprecifica de nuevo antes de crearse, así que nada se cobra mal.
    """
    company = company_svc.obtener_de_usuario(entrada.user_id)
    if not company:
        return {"aplicado": False, "motivo": "sin_empresa"}

    checkout = _checkout_del_usuario(entrada.checkout_id, entrada.user_id)
    if reprecio_mod.canal_de(checkout) not in config.CANALES:
        # El canal lo dice el carrito en Saleor, no quien llama: un carrito
        # retail se paga por la pasarela retail, sin pasar por /pedido, y un
        # precio por volumen fijado ahí se cobraría tal cual.
        return {"aplicado": False, "motivo": "canal_no_b2b"}
    try:
        return reprecio_mod.aplicar_a(checkout)
    except reprecio_mod.ReprecioError as exc:
        logger.error("(b2b) no se pudo reprecificar %s: %s", entrada.checkout_id, exc)
        raise HTTPException(502, "no se pudo actualizar el precio del carrito") from exc


# ─────────────────────────── pedido ───────────────────────────

class PedidoIn(BaseModel):
    checkout_id: str
    user_id: str
    metodo_pago: str


# El carrito ya no es el que se revisó: una cantidad negociada se alteró, o
# algo cambió mientras se confirmaba. Se revisa y se vuelve a intentar.
CARRITO_MODIFICADO = "CARRITO_MODIFICADO"


def _cantidades(checkout: dict) -> dict:
    return {l.get("id"): int(l.get("quantity") or 0)
            for l in checkout.get("lines") or []}


@app.post("/pedido", dependencies=SERVICIO)
def crear_pedido(entrada: PedidoIn) -> dict:
    """Cierra el carrito como orden con el medio de pago elegido.

    El pedido nace **por pagar**: en distribución mayorista la orden se despacha
    contra una promesa de pago, así que no se exige que el total esté cubierto.
    La identidad tributaria viaja en la metadata de la orden, que es lo que
    después permite facturar.

    El orden importa: todo lo que puede rechazar el pedido va antes de la
    primera escritura, y la orden se crea al final y una sola vez.

    Los rechazos responden `{"detail", "code"}`: el detalle en castellano para
    mostrar y el código para decidir. Los errores crudos de Saleor van solo al
    log: están en inglés y pueden nombrar campos internos.
    """
    checkout = _checkout_del_usuario(entrada.checkout_id, entrada.user_id)

    canal = reprecio_mod.canal_de(checkout)
    if canal not in config.CANALES:
        # Un pedido por pagar en un canal retail sería una venta que nadie
        # espera cobrar: allí se paga en el checkout normal.
        raise ErrorConCodigo(422, "este carrito no está en un canal de venta a empresas",
                             "CANAL_NO_B2B")

    company = company_svc.obtener_de_usuario(entrada.user_id)
    if not company:
        # 403 y no 404: aquí sí corresponde ser explícito. Comprar como empresa
        # es exactamente lo que este endpoint hace, y quien llama necesita saber
        # que le falta el alta para poder completarla.
        raise ErrorConCodigo(403, "el usuario no tiene empresa asociada", "SIN_EMPRESA")

    if not company_models.esta_aprobada(company):
        # Antes de cualquier escritura: ni reprecio ni orden. El carrito queda
        # tal cual para cuando el staff la apruebe. El código es el mismo motivo
        # con que `medios_pago` deshabilita los medios, para que el storefront
        # reconozca un solo nombre para este estado.
        raise ErrorConCodigo(403, EN_REVISION, "PENDIENTE_APROBACION")

    tiene_credito = company_models.tiene_credito(company)
    try:
        # Antes de reprecificar: si el medio no corresponde, el carrito no se toca.
        medios_mod.validar(entrada.metodo_pago, tiene_credito=tiene_credito)
    except medios_mod.MedioNoDisponible as exc:
        # 409: el medio existe, es el estado de esta empresa el que no lo admite.
        # El mensaje es nuestro, no de Saleor: se puede mostrar.
        raise ErrorConCodigo(409, str(exc), "MEDIO_NO_DISPONIBLE") from exc

    if cart.negociadas_alteradas(checkout.get("lines") or []):
        # Un precio negociado vale para la cantidad acordada, y Saleor lo
        # conserva cuando el cliente cambia solo la cantidad: sin esto, 500
        # unidades a precio de volumen se podían cerrar como 1 al mismo precio.
        raise ErrorConCodigo(409, "la cantidad de un producto con precio negociado ya "
                                  "no es la acordada; vuelve a esa cantidad o pide a tu "
                                  "ejecutivo un carrito nuevo", CARRITO_MODIFICADO)

    try:
        # El precio se recalcula aquí, en el servidor: el reprecio del
        # storefront es para mostrar, y un carrito cuya cantidad cambió
        # después conservaría un tramo que ya no le corresponde.
        reprecio_mod.aplicar_a(checkout)
    except (reprecio_mod.ReprecioError, SaleorError) as exc:
        logger.error("(b2b) reprecio previo al pedido falló (%s): %s",
                     entrada.checkout_id, exc)
        raise HTTPException(502, "no se pudo confirmar el precio del carrito; "
                                 "el pedido no se creó, intenta de nuevo") from exc

    try:
        pedido_svc.asegurar_facturacion(checkout)
    except pedido_svc.SinDireccion as exc:
        raise ErrorConCodigo(422, "falta la dirección de despacho del pedido",
                             "SHIPPING_ADDRESS_NOT_SET") from exc
    except pedido_svc.PedidoError as exc:
        logger.warning("(b2b) facturación rechazada en %s: %s", entrada.checkout_id, exc)
        raise ErrorConCodigo(422, "la dirección de despacho no sirve como dirección de "
                                  "facturación; revísala e intenta de nuevo",
                             "BILLING_ADDRESS_INVALID") from exc

    # Lo reprecificado y revisado es la foto leída al comienzo. Si una cantidad
    # cambió entretanto (otra pestaña, el carrito lateral), el precio fijado ya
    # no le corresponde y Saleor lo conservaría igual: se relee justo antes de
    # crear la orden. Queda una ventana de una consulta, no la de todo el flujo.
    vigente = reprecio_mod.leer_checkout(entrada.checkout_id)
    if not vigente:
        estado, mensaje = pedido_svc.explicar("CHECKOUT_NOT_FOUND")
        raise ErrorConCodigo(estado, mensaje, "CHECKOUT_NOT_FOUND")
    if _cantidades(vigente) != _cantidades(checkout):
        raise ErrorConCodigo(409, "el carrito cambió mientras se confirmaba el pedido; "
                                  "revísalo e intenta de nuevo", CARRITO_MODIFICADO)

    try:
        pedido = pedido_svc.crear(
            entrada.checkout_id,
            entrada.metodo_pago,
            tiene_credito=tiene_credito,
            extra_metadata=company.para_orden(company_id=entrada.user_id),
        )
    except medios_mod.MedioNoDisponible as exc:
        raise ErrorConCodigo(409, str(exc), "MEDIO_NO_DISPONIBLE") from exc
    except pedido_svc.OrdenRechazada as exc:
        # Warning y no error: casi siempre es el carrito (stock, despacho), no
        # la integración. Igual queda el detalle para quien tenga que revisarlo.
        logger.warning("(b2b) Saleor rechazó la orden de %s: %s",
                       entrada.checkout_id, exc.errores)
        estado, mensaje = pedido_svc.explicar(exc.codigo)
        raise ErrorConCodigo(estado, mensaje, exc.codigo or "ORDEN_RECHAZADA") from exc
    except pedido_svc.PedidoError as exc:
        logger.warning("(b2b) pedido rechazado en %s: %s", entrada.checkout_id, exc)
        estado, mensaje = pedido_svc.explicar("")
        raise ErrorConCodigo(estado, mensaje, "ORDEN_RECHAZADA") from exc
    except SaleorTimeoutError as exc:
        # No se reintenta: Saleor pudo haber creado la orden. Se le dice al
        # cliente que revise antes de repetir, para no duplicar el pedido.
        logger.error("(b2b) timeout al crear la orden de %s: %s", entrada.checkout_id, exc)
        raise HTTPException(504, "Saleor no confirmó el pedido a tiempo; revisa tus "
                                 "pedidos antes de intentarlo de nuevo") from exc

    return {
        "order_id": pedido.order_id,
        "numero": pedido.numero,
        "estado": pedido.estado,
        "total": pedido.total,
        "moneda": pedido.moneda,
        "metodo_pago": pedido.metodo_pago,
        "estado_pago": medios_mod.PENDIENTE,
        # Datos para pagar por transferencia. `null` si no están configurados:
        # mejor que el storefront diga «te contactaremos» que inventar una cuenta.
        "instrucciones_pago": (config.INSTRUCCIONES_TRANSFERENCIA
                               if pedido.metodo_pago == medios_mod.TRANSFERENCIA
                               else None),
    }
