"""Configuración de la App B2B (variables de entorno)."""

import os
from typing import List


def _lista(valor: str) -> List[str]:
    return [p.strip() for p in valor.split(",") if p.strip()]


SALEOR_API_URL = os.getenv("SALEOR_API_URL", "")
SALEOR_AUTH_TOKEN = os.getenv("SALEOR_AUTH_TOKEN", "")

# Token con el que se leen la escalera de tramos y el costo. Ambos viven en la
# metadata **privada** del producto, y leerla exige `MANAGE_PRODUCTS`: un permiso
# de escritura sobre los 22.765 artículos del catálogo.
#
# Se separa para no tener que ampliar los permisos de esta app entera, que sobre
# el catálogo solo necesita leer. Vacío = usa el token propio.
SALEOR_PRODUCTS_TOKEN = os.getenv("SALEOR_PRODUCTS_TOKEN", "") or SALEOR_AUTH_TOKEN

# Canal por defecto de una empresa recién registrada. Se separa del canal en que
# se arman los carritos de WhatsApp: una empresa nueva parte en retail hasta que
# se le asigna nivel mayorista.
DEFAULT_NIVEL_PRECIO = os.getenv("B2B_DEFAULT_NIVEL_PRECIO", "retail-cl")

# Canal en que se crean los carritos enviados por WhatsApp. Nacen directamente
# en B2B por decisión de producto: el ejecutivo ya sabe que habla con una
# empresa, y así el carrito no necesita reconstruirse al identificarse.
CANAL_CARRITO = os.getenv("B2B_CANAL_CARRITO", "b2b-cl")

# Base pública para los enlaces de carrito enviados por WhatsApp.
STOREFRONT_URL = os.getenv("STOREFRONT_URL", "").rstrip("/")

# Tamaño máximo de la Carpeta Tributaria. Existe para acotar lo que el proceso
# llega a tener en memoria: el documento no se persiste, se reenvía.
CARPETA_MAX_BYTES = int(os.getenv("B2B_CARPETA_MAX_BYTES", str(15 * 1024 * 1024)))


def tramos_del_canal(channel_slug: str) -> str:
    """Escalera por defecto del channel, si la tiene.

    Es el último recurso: manda la del producto. Existe para no tener que cargar
    una tabla por cada uno de los 22.765 artículos cuando la regla es general.
    """
    key = "PRICING_TIERS_" + channel_slug.upper().replace("-", "_")
    return os.getenv(key, os.getenv("PRICING_TIERS", ""))


# ── margen mínimo en precios negociados ──
# Utilidad neta sobre el costo por debajo de la cual un precio negociado se
# rechaza. Vacío desactiva la revisión: sin costo publicado no hay nada que
# comparar, y bloquear ventas por un dato ausente sería peor que no revisar.
MARKUP_MINIMO = float(os.getenv("B2B_MARKUP_MINIMO", "0") or 0)

# Comisión de la pasarela de pago, que se descuenta de cada venta. Sin esto un
# markup del 30% con una pasarela del 3% deja 26,1% real.
COMISION_PASARELA = float(os.getenv("B2B_COMISION_PASARELA", "0") or 0)


# Stock por debajo del cual no se publican tramos por volumen: con pocas
# unidades, ofrecer precio por cantidad promete algo que no se puede cumplir.
STOCK_MINIMO_TRAMOS = int(os.getenv("B2B_STOCK_MINIMO_TRAMOS", "0") or 0)


# ── autenticación ──
# El servicio es alcanzable desde internet y actúa sobre Saleor con permisos de
# app (MANAGE_USERS, HANDLE_CHECKOUTS): sin token, cualquiera podría leer la
# empresa de un usuario o cerrar un carrito ajeno como pedido.
#
# Dos credenciales porque hay dos llamadores con confianza distinta:
# - SERVICE_TOKEN lo envía el servidor del storefront en nombre del cliente.
# - STAFF_TOKEN lo usan las herramientas internas: fijar el nivel de precio,
#   registrar el veredicto de crédito, armar carritos con precio negociado.
# Filtrarse el del storefront no debe permitir aprobarse crédito a uno mismo.
#
# Ambos vacíos = **cerrado**: toda ruta con datos responde 503. Abrir la API
# sin tokens exige pedirlo con B2B_AUTH_ABIERTA=1, solo en desarrollo local. Un
# entorno nuevo, un servicio clonado o una variable renombrada dejan la API
# cerrada en vez de dejarla abierta en silencio.
SERVICE_TOKEN = os.getenv("B2B_SERVICE_TOKEN", "").strip()
STAFF_TOKEN = os.getenv("B2B_STAFF_TOKEN", "").strip()
# Sin efecto si hay algún token configurado: los tokens siempre mandan.
AUTH_ABIERTA = os.getenv("B2B_AUTH_ABIERTA", "").strip() == "1"

# Canales en que se vende como empresa. Un pedido B2B (por pagar, con identidad
# tributaria) solo tiene sentido en ellos; en retail sería un pedido impago que
# nadie espera cobrar. Vacío se trata como el valor por defecto.
CANALES = _lista(os.getenv("B2B_CANALES", "") or "b2b-cl")

# Niveles de precio que el staff puede asignar a una empresa. Lista cerrada para
# que un error de tipeo no deje a una empresa en un canal inexistente, donde
# ningún producto tiene precio.
NIVELES_PERMITIDOS = _lista(os.getenv("B2B_NIVELES_PERMITIDOS", "")
                            or "retail-cl,b2b-cl")

# Datos bancarios que se muestran al cerrar un pedido por transferencia. Vacío
# = `null`: mejor no mostrar nada que una cuenta inventada.
INSTRUCCIONES_TRANSFERENCIA = os.getenv("B2B_INSTRUCCIONES_TRANSFERENCIA", "") or None

# URL pública de la app, para el manifest. Detrás del proxy de Railway el
# proceso ve http y Saleor rechaza instalar una app que se anuncia sin TLS.
PUBLIC_URL = os.getenv("B2B_PUBLIC_URL", "").strip().rstrip("/")

# ── avisos al cliente (Ventu Correo) ──
# Servicio de correo del proyecto y su token de /enviar. Cualquiera de los dos
# vacío = no se avisa: la aprobación sigue funcionando y la respuesta del
# PATCH dice que el correo no salió, para que el staff avise a mano.
CORREO_URL = os.getenv("CORREO_URL", "").strip().rstrip("/")
CORREO_SERVICE_TOKEN = os.getenv("CORREO_SERVICE_TOKEN", "").strip()
