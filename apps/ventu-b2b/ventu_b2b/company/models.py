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

- `metadata`      → lo que hace falta buscar y no revela condiciones comerciales
                    (RUT, razón social: aparecen en cualquier factura)
- `privateMetadata` → lo que sí las revela (nivel de precio, estado de crédito)

Ninguno de los dos es legible por un anónimo: leer un usuario en Saleor exige
autenticación. La distinción es entre "buscable" y "condición comercial".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

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


class CompanyInvalida(ValueError):
    """Los datos de la empresa no permiten operar."""


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
        """Claves buscables. El RUT va aquí porque es la clave de búsqueda."""
        return {
            K_RUT: self.rut,
            K_RAZON: self.razon_social,
            **({K_GIRO: self.giro} if self.giro else {}),
            **({K_TELEFONO: self.telefono} if self.telefono else {}),
        }

    def to_private_metadata(self) -> Dict[str, str]:
        """Condiciones comerciales: no deben ser buscables ni visibles de más."""
        return {
            K_NIVEL: self.nivel_precio,
            K_CONDICION: self.condicion_pago,
            K_CREDITO: self.credito_estado,
            **({K_CREDITO_REF: self.credito_ref} if self.credito_ref else {}),
        }

    # ── reconstrucción desde Saleor ──

    @classmethod
    def from_metadata(cls, meta: Dict[str, str],
                      private: Optional[Dict[str, str]] = None) -> "Company":
        private = private or {}
        if not meta.get(K_RUT):
            raise CompanyInvalida("el usuario no tiene empresa asociada")
        return cls(
            rut=meta[K_RUT],
            razon_social=meta.get(K_RAZON, ""),
            giro=meta.get(K_GIRO, ""),
            telefono=meta.get(K_TELEFONO, ""),
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


def tiene_credito(company: Company) -> bool:
    """¿Puede pagar a plazo hoy?

    Exige las dos cosas: crédito aprobado **y** condición de pago a crédito. Una
    empresa aprobada que sigue comprando al contado no debe pasar a plazo sola.
    """
    return (company.credito_estado == "aprobada"
            and company.condicion_pago == "credito_30")
