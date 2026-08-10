"""Tests del modelo Company: puros, sin red."""

from __future__ import annotations

import pytest

from ventu_b2b.company import rut as rut_mod
from ventu_b2b.company.models import (
    K_CREDITO,
    K_NIVEL,
    K_RAZON,
    K_RUT,
    Company,
    CompanyInvalida,
    tiene_credito,
)

RUT_OK = "76.543.210-3"
RUT_CANON = "76543210-3"


def _company(**kw):
    base = dict(rut=RUT_OK, razon_social="Comercial Ventu SpA")
    base.update(kw)
    return Company(**base)


# ───────────────────────── construcción ─────────────────────────

def test_normaliza_el_rut_al_construir():
    """Una Company no debe existir con el RUT en formato libre, venga de donde
    venga."""
    assert _company().rut == RUT_CANON
    assert _company(rut="765432103").rut == RUT_CANON


def test_rechaza_rut_invalido():
    with pytest.raises(rut_mod.RutInvalido):
        _company(rut="76.543.210-9")


def test_rechaza_razon_social_vacia():
    for vacia in ("", "   "):
        with pytest.raises(CompanyInvalida, match="razón social"):
            _company(razon_social=vacia)


def test_recorta_espacios_en_razon_social():
    assert _company(razon_social="  Ventu SpA  ").razon_social == "Ventu SpA"


@pytest.mark.parametrize("campo,valor", [
    ("condicion_pago", "cheque_a_30"),
    ("credito_estado", "en_revision"),
])
def test_rechaza_valores_desconocidos(campo, valor):
    with pytest.raises(CompanyInvalida):
        _company(**{campo: valor})


# ───────────────── reparto metadata / privateMetadata ─────────────────

def test_el_rut_va_en_metadata_buscable():
    """Saleor solo permite filtrar clientes por `metadata`, no por
    `privateMetadata`. Si el RUT quedara del lado privado no se podría
    responder «¿esta empresa ya existe?»."""
    meta = _company().to_metadata()
    assert meta[K_RUT] == RUT_CANON
    assert meta[K_RAZON] == "Comercial Ventu SpA"


def test_las_condiciones_comerciales_no_van_en_metadata():
    c = _company(nivel_precio="b2b-cl", credito_estado="aprobada")
    meta = c.to_metadata()
    assert K_NIVEL not in meta
    assert K_CREDITO not in meta
    priv = c.to_private_metadata()
    assert priv[K_NIVEL] == "b2b-cl"
    assert priv[K_CREDITO] == "aprobada"


def test_campos_opcionales_vacios_no_se_escriben():
    """Escribir claves vacías ensucia la metadata y confunde al leerla."""
    meta = _company().to_metadata()
    assert "ventu.b2b.giro" not in meta
    assert "ventu.b2b.telefono" not in meta


# ───────────────────────── ida y vuelta ─────────────────────────

def test_ida_y_vuelta_conserva_todo():
    original = _company(giro="Comercio al por mayor", telefono="+56911111111",
                        nivel_precio="b2b-cl", condicion_pago="credito_30",
                        credito_estado="aprobada", credito_ref="MX-99")
    recuperada = Company.from_metadata(original.to_metadata(),
                                       original.to_private_metadata())
    assert recuperada == original


def test_usuario_sin_empresa_es_explicito():
    with pytest.raises(CompanyInvalida, match="no tiene empresa"):
        Company.from_metadata({}, {})


def test_sin_privatemetadata_cae_a_los_valores_por_defecto():
    """Un usuario con RUT pero sin condiciones aún no debe romper la lectura."""
    c = Company.from_metadata({K_RUT: RUT_CANON, K_RAZON: "Ventu SpA"})
    assert c.nivel_precio == "retail-cl"
    assert c.condicion_pago == "contado"
    assert c.credito_estado == "sin_solicitud"


# ───────────────────────── datos para la orden ─────────────────────────

def test_para_orden_copia_los_valores():
    """Copia, no referencia: si la empresa cambia de razón social, las facturas
    ya emitidas no deben cambiar."""
    datos = _company().para_orden(company_id="VXNlcjo1")
    assert datos[K_RUT] == RUT_CANON
    assert datos[K_RAZON] == "Comercial Ventu SpA"
    assert datos["ventu.b2b.company_id"] == "VXNlcjo1"


# ───────────────────────── crédito ─────────────────────────

def test_credito_exige_aprobacion_y_condicion():
    assert tiene_credito(_company(credito_estado="aprobada",
                                  condicion_pago="credito_30")) is True


def test_aprobada_pero_al_contado_no_paga_a_plazo():
    """Una empresa aprobada que sigue comprando al contado no debe pasar a plazo
    por sí sola."""
    assert tiene_credito(_company(credito_estado="aprobada",
                                  condicion_pago="contado")) is False


def test_condicion_credito_sin_aprobacion_no_basta():
    assert tiene_credito(_company(credito_estado="pendiente",
                                  condicion_pago="credito_30")) is False
