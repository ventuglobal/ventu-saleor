"""Company: la empresa que mantiene la relación comercial con Ventu.

Vive en la metadata del usuario de Saleor. En 1.0 la relación es 1 usuario = 1
empresa, lo que permite prescindir de base de datos propia — coherente con las
demás apps de Ventu, que son sin estado.

**Por qué los campos se reparten entre `metadata` y `privateMetadata`.** Saleor
permite filtrar clientes por `metadata` (`CustomerFilterInput.metadata`) pero
**no** por `privateMetadata`. Buscar una empresa por su RUT es la operación más
frecuente del MVP —es la que resuelve «¿esta empresa ya existe?»— así que el RUT
tiene que estar del lado indexable.

El reparto entonces es:

- `metadata`      → índice de búsqueda y copia para mostrar: RUT, razón social
                    (aparecen en cualquier factura) y el estado de aprobación,
                    para listar las empresas en revisión
- `privateMetadata` → la fuente de verdad: la identidad (RUT, razón social,
                    giro, teléfono) y las condiciones comerciales (nivel de
                    precio, estado de crédito)

**Por qué la identidad también va en la privada, y manda esa.** Saleor deja que
un cliente escriba la `metadata` pública de su propio usuario sin permiso alguno
(`public_user_permissions`); la privada exige MANAGE_USERS, o sea, solo la
escribe esta app. Si el RUT se leyera de la pública, un cliente aprobado podría
cambiarlo después de la revisión y facturar a nombre de otro, ocupar el RUT de
otra empresa o inventarse una sin pasar por el alta. La copia pública queda
solo para buscar; nada de lo que decide se lee de ahí.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from .. import config
from . import rut as rut_mod

# Prefijo de todas las claves, para no colisionar con metadata de otras apps.
NS = "ventu.b2b"

K_RUT = f"{NS}.rut"
K_RAZON = f"{NS}.razon_social"
K_GIRO = f"{NS}.giro"
K_TELEFONO = f"{NS}.telefono"
K_NIVEL = f"{NS}.nivel_precio"
K_CONDICION = f"{NS}.condicion_pago"
K_CREDITO = f"{NS}.credito_estado"
K_CREDITO_REF = f"{NS}.credito_ref"
# Espejo público de la aprobación (ver `esta_aprobada`). Público porque es lo
# único que Saleor deja filtrar: sin él, encontrar las empresas en revisión
# obligaría a recorrer todos los clientes.
K_ESTADO = f"{NS}.estado"

ESTADO_PENDIENTE = "pendiente"
ESTADO_APROBADA = "aprobada"


class CompanyInvalida(ValueError):
    """Los datos de la empresa no permiten operar."""


class SinEmpresa(CompanyInvalida):
    """El usuario no tiene empresa: el estado normal de quien recién se registra.

    Se distingue del resto de `CompanyInvalida` para no confundir «no hay
    empresa» con «hay una empresa que no se puede leer», que sí merece aviso.
    """


# Estados de la solicitud de crédito. `sin_solicitud` es el inicial: una empresa
# puede comprar al contado sin haber pedido crédito nunca.
CREDITO_ESTADOS = ("sin_solicitud", "pendiente", "aprobada", "rechazada")

CONDICIONES_PAGO = ("contado", "credito_30")


@dataclass
class Company:
    rut: str                     # forma canónica (ver company.rut)
    razon_social: str
    giro: str = ""
    telefono: str = ""
    # Canal en que compra. Determina su lista de precios.
    nivel_precio: str = "retail-cl"
    # Independiente del nivel de precio: una empresa puede tener precio
    # mayorista y pagar al contado, y será el caso mayoritario al inicio.
    condicion_pago: str = "contado"
    credito_estado: str = "sin_solicitud"
    credito_ref: str = ""

    def __post_init__(self) -> None:
        # El RUT se normaliza aquí y no en el borde: así una Company nunca existe
        # con un RUT en formato libre, cualquiera sea la vía de construcción.
        self.rut = rut_mod.normalizar(self.rut)

        if not self.razon_social or not self.razon_social.strip():
            raise CompanyInvalida("razón social vacía")
        self.razon_social = self.razon_social.strip()

        if self.condicion_pago not in CONDICIONES_PAGO:
            raise CompanyInvalida(
                f"condición de pago desconocida: {self.condicion_pago!r}")
        if self.credito_estado not in CREDITO_ESTADOS:
            raise CompanyInvalida(
                f"estado de crédito desconocido: {self.credito_estado!r}")

    # ── serialización hacia Saleor ──

    def to_metadata(self) -> Dict[str, str]:
        """Índice buscable. El RUT va aquí porque es la clave de búsqueda; lo
        que vale es la copia privada.

        Incluye el espejo del estado, derivado del nivel: así el alta lo deja
        escrito y la empresa aparece de inmediato entre las pendientes.
        """
        return {
            K_RUT: self.rut,
            K_RAZON: self.razon_social,
            **({K_GIRO: self.giro} if self.giro else {}),
            **({K_TELEFONO: self.telefono} if self.telefono else {}),
            K_ESTADO: estado_de(self),
        }

    def to_private_metadata(self) -> Dict[str, str]:
        """La fuente de verdad: identidad y condiciones comerciales.

        La identidad se repite aquí porque la copia pública la puede reescribir
        el propio cliente (ver el docstring del módulo).
        """
        return {
            K_RUT: self.rut,
            K_RAZON: self.razon_social,
            **({K_GIRO: self.giro} if self.giro else {}),
            **({K_TELEFONO: self.telefono} if self.telefono else {}),
            K_NIVEL: self.nivel_precio,
            K_CONDICION: self.condicion_pago,
            K_CREDITO: self.credito_estado,
            **({K_CREDITO_REF: self.credito_ref} if self.credito_ref else {}),
        }

    # ── reconstrucción desde Saleor ──

    @classmethod
    def from_metadata(cls, meta: Dict[str, str],
                      private: Optional[Dict[str, str]] = None) -> "Company":
        """Reconstruye la empresa. La identidad sale de la metadata privada.

        Empresas anteriores a la copia privada: se leen de la pública solo si
        la privada tiene el nivel de precio, que el alta siempre escribió y que
        un cliente no puede escribir. Así una empresa inventada a mano en la
        pública no existe para la app. El PATCH del staff congela esa identidad
        en la privada (ver `service.actualizar`).
        """
        private = private or {}
        if private.get(K_RUT):
            identidad = private
        elif meta.get(K_RUT) and private.get(K_NIVEL):
            identidad = meta
        else:
            raise SinEmpresa("el usuario no tiene empresa asociada")
        return cls(
            rut=identidad[K_RUT],
            razon_social=identidad.get(K_RAZON, ""),
            giro=identidad.get(K_GIRO, ""),
            telefono=identidad.get(K_TELEFONO, ""),
            nivel_precio=private.get(K_NIVEL, "retail-cl"),
            condicion_pago=private.get(K_CONDICION, "contado"),
            credito_estado=private.get(K_CREDITO, "sin_solicitud"),
            credito_ref=private.get(K_CREDITO_REF, ""),
        )

    # ── datos que viajan a la orden ──

    def para_orden(self, company_id: str = "") -> Dict[str, str]:
        """Identidad tributaria que se copia al checkout y de ahí a la orden.

        Se copian los valores, no una referencia: un documento tributario refleja
        los datos al momento de la compra. Si la empresa cambia de razón social,
        las facturas ya emitidas no deben cambiar con ella.
        """
        return {
            f"{NS}.company_id": company_id,
            K_RUT: self.rut,
            K_RAZON: self.razon_social,
        }


def esta_aprobada(company: Company) -> bool:
    """¿Ventu ya revisó esta empresa y la habilitó para comprar?

    Se deriva del nivel de precio y no de `K_ESTADO`: el nivel es lo que el
    staff asigna y lo que decide el precio, así que es la fuente de verdad. El
    espejo público solo sirve para buscar, y una empresa anterior a él —que no
    lo tiene— se sigue leyendo bien.

    Aprobada = compra en un canal B2B (`B2B_CANALES`). El alta la deja en el
    nivel por defecto (`retail-cl`), o sea en revisión.
    """
    return company.nivel_precio in config.CANALES


def estado_de(company: Company) -> str:
    """El valor que corresponde escribir en `K_ESTADO`."""
    return ESTADO_APROBADA if esta_aprobada(company) else ESTADO_PENDIENTE


def tiene_credito(company: Company) -> bool:
    """¿Puede pagar a plazo hoy?

    Exige las dos cosas: crédito aprobado **y** condición de pago a crédito. Una
    empresa aprobada que sigue comprando al contado no debe pasar a plazo sola.
    """
    return (company.credito_estado == "aprobada"
            and company.condicion_pago == "credito_30")
