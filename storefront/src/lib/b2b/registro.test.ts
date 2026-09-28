import { describe, expect, it } from "vitest";

import { empresaDelRegistro } from "./registro";

describe("empresaDelRegistro", () => {
	it("en un canal de empresa exige RUT y razón social", () => {
		expect(empresaDelRegistro(true, "", "Santa Teresa")).toEqual({ ok: false });
		expect(empresaDelRegistro(true, "76.543.210-3", "")).toEqual({ ok: false });
		expect(empresaDelRegistro(true, undefined, undefined)).toEqual({ ok: false });
	});

	it("en un canal de empresa, espacios en blanco no cuentan como dato", () => {
		expect(empresaDelRegistro(true, "   ", "  ")).toEqual({ ok: false });
	});

	it("en un canal de empresa entrega los datos sin espacios sobrantes", () => {
		expect(empresaDelRegistro(true, " 76.543.210-3 ", " Comercial Santa Teresa SpA ")).toEqual({
			ok: true,
			empresa: { rut: "76.543.210-3", razonSocial: "Comercial Santa Teresa SpA" },
		});
	});

	it("en retail no exige nada", () => {
		expect(empresaDelRegistro(false, "", "")).toEqual({ ok: true, empresa: null });
		expect(empresaDelRegistro(false)).toEqual({ ok: true, empresa: null });
	});

	it("en retail ignora un RUT aunque venga", () => {
		// Asociar una empresa en un canal retail la dejaría con precios y medios de
		// pago de empresa que nadie pidió.
		expect(empresaDelRegistro(false, "76.543.210-3", "Santa Teresa")).toEqual({ ok: true, empresa: null });
	});
});
