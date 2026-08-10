"""App B2B de Ventu.

Aporta identidad empresarial y continuidad comercial sobre Saleor:

- identifica una empresa por su RUT y la asocia al usuario
- convierte una conversación de WhatsApp en un carrito recuperable por enlace
- cuelga la identidad tributaria del checkout para que llegue a la orden

Es su propia Saleor App porque necesita `MANAGE_USERS` (escribir la metadata del
cliente) y `HANDLE_CHECKOUTS` (fijar el precio de una línea), permisos que las
demás apps de Ventu no tienen ni necesitan.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import config
from .cart import link as link_mod
from .cart import service as cart
from .company import rut as rut_mod
from .company import service as company_svc
from .credito import estados as credito_st
from .credito import service as credito_svc
from .company.models import Company, CompanyInvalida

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ventu-b2b")

app = FastAPI(title="Ventu B2B", version="0.1.0")


# ─────────────────────────── infra ───────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/manifest")
async def manifest(request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    return {
        "id": "cl.ventu.b2b",
        "version": "0.1.0",
        "name": "Ventu B2B",
        "about": "Identidad empresarial y carritos de WhatsApp sobre Saleor.",
        "permissions": ["MANAGE_USERS", "HANDLE_CHECKOUTS", "MANAGE_CHECKOUTS"],
        "appUrl": base,
        "tokenTargetUrl": f"{base}/register",
        "webhooks": [],
    }


@app.post("/register")
async def register(request: Request) -> dict:
    """Recibe el token de instalación de Saleor."""
    body = await request.json()
    token = body.get("auth_token")
    if not token:
        raise HTTPException(400, "falta auth_token")
    logger.info("(b2b) app registrada en Saleor")
    return {"status": "ok"}


# ─────────────────────────── empresas ───────────────────────────

class CompanyIn(BaseModel):
    user_id: str
    rut: str
    razon_social: str
    giro: str = ""
    telefono: str = ""
    nivel_precio: Optional[str] = None


@app.post("/company")
async def registrar_empresa(entrada: CompanyIn) -> dict:
    """Da de alta la empresa y la asocia al usuario."""
    try:
        company = Company(
            rut=entrada.rut,
            razon_social=entrada.razon_social,
            giro=entrada.giro,
            telefono=entrada.telefono,
            nivel_precio=entrada.nivel_precio or config.DEFAULT_NIVEL_PRECIO,
        )
    except (rut_mod.RutInvalido, CompanyInvalida) as exc:
        # 422: el dato es inválido, no es un fallo del servidor.
        raise HTTPException(422, str(exc)) from exc

    try:
        company_svc.registrar(entrada.user_id, company)
    except company_svc.EmpresaYaRegistrada as exc:
        # 409 y no 400: el conflicto es con el estado actual, no con la petición.
        # Es el caso del colega de la misma empresa y merece respuesta propia.
        raise HTTPException(409, str(exc)) from exc

    return {"status": "ok", "rut": company.rut,
            "nivel_precio": company.nivel_precio}


@app.get("/company/por-rut/{rut_libre}")
async def buscar_empresa(rut_libre: str) -> dict:
    """¿Este RUT ya está registrado? Normaliza antes de buscar."""
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
    # La hora la fija quien llama para que el registro de auditoría no dependa
    # del reloj del proceso y sea reproducible.
    ahora: str


@app.post("/credito/solicitar")
async def solicitar_credito(entrada: CreditoIn) -> dict:
    """Abre una solicitud. Paso voluntario: no bloquea la compra al contado."""
    company = company_svc.obtener_de_usuario(entrada.user_id)
    if not company:
        raise HTTPException(404, "el usuario no tiene empresa asociada")
    try:
        s = credito_svc.solicitar(entrada.user_id, company, ahora=entrada.ahora)
    except credito_st.TransicionInvalida as exc:
        # 409: el conflicto es con el estado actual (p. ej. ya hay una solicitud
        # en curso), no con la petición.
        raise HTTPException(409, str(exc)) from exc
    return {"estado": s.estado, "rut": s.company_rut}


class VeredictoIn(BaseModel):
    user_id: str
    veredicto: str
    referencia: str = ""
    ahora: str


@app.post("/credito/resolver")
async def resolver_credito(entrada: VeredictoIn) -> dict:
    """Registra el resultado devuelto por Maxxa."""
    company = company_svc.obtener_de_usuario(entrada.user_id)
    if not company:
        raise HTTPException(404, "el usuario no tiene empresa asociada")
    try:
        s = credito_svc.resolver(entrada.user_id, company, entrada.veredicto,
                                 ahora=entrada.ahora, referencia=entrada.referencia)
    except credito_st.TransicionInvalida as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"estado": s.estado, "referencia": s.referencia}


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


@app.post("/cart")
async def crear_carrito(entrada: CarritoIn) -> dict:
    """Arma el carrito y devuelve el enlace para enviar por WhatsApp."""
    if not entrada.lineas:
        raise HTTPException(422, "un carrito sin líneas no es una propuesta")

    extra = {}
    if entrada.user_id:
        company = company_svc.obtener_de_usuario(entrada.user_id)
        if company:
            # La identidad tributaria viaja con el carrito para llegar a la
            # orden: es lo que después permite facturar.
            extra = company.para_orden(company_id=entrada.user_id)

    try:
        carrito = cart.crear(
            [cart.Linea(l.variant_id, l.cantidad, l.precio_unitario)
             for l in entrada.lineas],
            canal=entrada.canal or "",
            origen=entrada.origen,
            extra_metadata=extra,
        )
    except cart.CarritoError as exc:
        raise HTTPException(422, str(exc)) from exc

    if entrada.user_id:
        cart.adjuntar_cliente(carrito.checkout_id, entrada.user_id)

    return {"link_id": carrito.link_id, "url": carrito.url(),
            "checkout_id": carrito.checkout_id}


@app.get("/cart/{link_id}")
async def resolver_carrito(link_id: str) -> dict:
    """Resuelve el enlace hacia el carrito vigente."""
    if not link_mod.es_valido(link_id):
        raise HTTPException(404, "enlace no encontrado")

    nodo = cart.resolver(link_id)
    if not nodo:
        # 410 y no 404: el enlace fue válido y ya no lo es. Permite al
        # storefront ofrecer rehacer el carrito en vez de mostrar "no existe".
        raise HTTPException(410, "el carrito ya no está disponible")

    return {"checkout_id": nodo["id"], "token": nodo.get("token"),
            "canal": (nodo.get("channel") or {}).get("slug")}
