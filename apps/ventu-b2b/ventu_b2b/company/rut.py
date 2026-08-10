"""RUT chileno: normalización y validación (módulo 11).

El RUT es el identificador de la empresa en todo Ventu — lo usan Facturación
para emitir el DTE y B2B para relacionar órdenes. Si entra en formatos distintos
(`76.543.210-K`, `76543210-k`, `765432107`), la misma empresa aparece como
varias y la unicidad deja de funcionar. Por eso se normaliza a una sola forma
canónica antes de guardar o comparar.

Puro: sin red ni estado.
"""

from __future__ import annotations

import re

# Forma canónica: dígitos sin puntos + guion + verificador en mayúscula.
_CANONICO = re.compile(r"^\d{7,8}-[\dK]$")
_SOLO_VALIDOS = re.compile(r"[^\dkK]")


class RutInvalido(ValueError):
    """El RUT no es sintácticamente válido o su dígito verificador no calza."""


def digito_verificador(cuerpo: str) -> str:
    """Dígito verificador por módulo 11, sobre el cuerpo sin puntos ni guion."""
    suma = 0
    factor = 2
    for digito in reversed(cuerpo):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "K"
    return str(resto)


def normalizar(valor: str) -> str:
    """Devuelve el RUT en forma canónica `12345678-9`, o lanza `RutInvalido`.

    Acepta puntos, guion opcional y verificador en minúscula. Valida el dígito
    verificador: un RUT con formato correcto pero verificador equivocado es un
    error de digitación, no un RUT.
    """
    if not valor or not valor.strip():
        raise RutInvalido("RUT vacío")

    limpio = _SOLO_VALIDOS.sub("", valor).upper()
    if len(limpio) < 8 or len(limpio) > 9:
        raise RutInvalido(f"largo inválido: {valor!r}")

    cuerpo, verificador = limpio[:-1], limpio[-1]
    if not cuerpo.isdigit():
        raise RutInvalido(f"el cuerpo debe ser numérico: {valor!r}")

    esperado = digito_verificador(cuerpo)
    if verificador != esperado:
        raise RutInvalido(
            f"dígito verificador incorrecto en {valor!r}: es {verificador}, debería ser {esperado}"
        )

    return f"{cuerpo}-{verificador}"


def es_valido(valor: str) -> bool:
    """Versión no lanzadora de `normalizar`, para validaciones de formulario."""
    try:
        normalizar(valor)
    except RutInvalido:
        return False
    return True


def formatear(rut_canonico: str) -> str:
    """Forma legible con puntos (`76.543.210-K`), solo para mostrar al usuario.

    Nunca se almacena así: lo persistido es siempre la forma canónica.
    """
    if not _CANONICO.match(rut_canonico):
        raise RutInvalido(f"no está en forma canónica: {rut_canonico!r}")
    cuerpo, verificador = rut_canonico.split("-")
    partes = []
    while len(cuerpo) > 3:
        partes.insert(0, cuerpo[-3:])
        cuerpo = cuerpo[:-3]
    partes.insert(0, cuerpo)
    return f"{'.'.join(partes)}-{verificador}"
