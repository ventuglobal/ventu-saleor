"""Registro de auditoría acotado, guardado en la metadata privada del usuario.

La metadata se sobrescribe clave a clave: escribir cada cambio en la misma
clave deja solo el último, y entonces «¿por qué esta empresa tiene crédito
aprobado?» o «¿quién le dio precio mayorista?» no tienen respuesta. Aquí cada
cambio se **agrega** a una lista JSON que conserva las últimas entradas.

No es un almacén append-only de verdad —quien tenga `MANAGE_USERS` puede
reescribir la clave, y dos escrituras simultáneas pueden pisarse— pero al
volumen del MVP cubre la pregunta que importa sin sumar una base de datos a una
app que hoy no tiene estado propio.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List

# Tope de entradas. Acota el tamaño de la metadata del usuario, que Saleor
# devuelve completa en cada lectura del cliente.
MAX_ENTRADAS = 50


def ahora_utc() -> str:
    """Hora del servidor en UTC, al segundo.

    La fija el servidor y no quien llama: una hora provista por el cliente
    permite fechar una aprobación cuando convenga.
    """
    return (datetime.now(timezone.utc).replace(microsecond=0)
            .isoformat().replace("+00:00", "Z"))


def leer(crudo: str) -> List[dict]:
    """Historial desde el valor guardado.

    Un valor que no es una lista —el formato anterior guardaba una sola línea—
    se conserva como entrada `legado` en vez de descartarse: es historia real.
    """
    if not crudo:
        return []
    try:
        valor = json.loads(crudo)
    except ValueError:
        return [{"legado": crudo}]
    if isinstance(valor, list):
        return valor
    return [{"legado": crudo}]


def anexar(crudo: str, entrada: dict, *, maximo: int = MAX_ENTRADAS) -> str:
    """Valor nuevo de la clave: el historial previo más `entrada`, recortado."""
    historial = leer(crudo)
    historial.append(entrada)
    return json.dumps(historial[-maximo:], ensure_ascii=False,
                      separators=(",", ":"))
