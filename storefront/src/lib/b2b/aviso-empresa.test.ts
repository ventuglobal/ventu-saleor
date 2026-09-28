import { describe, expect, it } from "vitest";

import { avisoDeEmpresa } from "./aviso-empresa";
import type { Empresa } from "./company";

const EMPRESA: Empresa = {
	registrada: true,
	aprobada: true,
	estado: "aprobada",
	rut: "76086428-5",
	razon_social: "Ferretería Los Andes SpA",
	nivel_precio: "mayorista",
	condicion_pago: "contado",
	credito_estado: "sin_linea",
	medios_pago: [],
};

describe("avisoDeEmpresa", () => {
	it("invita a registrar la empresa a quien no tiene", () => {
		expect(avisoDeEmpresa({ registrada: false })).toBe("sin_empresa");
	});

	it("no avisa nada si la App B2B no contestó: podría tener empresa", () => {
		expect(avisoDeEmpresa({ registrada: false, error: true })).toBeNull();
	});

	it("avisa que la empresa está en revisión mientras no la aprueben", () => {
		expect(avisoDeEmpresa({ ...EMPRESA, aprobada: false, estado: "pendiente" })).toBe("en_revision");
	});

	it("no avisa nada a una empresa aprobada", () => {
		expect(avisoDeEmpresa(EMPRESA)).toBeNull();
	});
});
