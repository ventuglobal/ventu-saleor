import { describe, expect, it } from "vitest";

import { estadoMediosPago, estadoTrasRechazoDePedido, medioPreseleccionado } from "./estado-medios-pago";

const MEDIOS = [
	{ codigo: "transferencia", etiqueta: "Transferencia", diferido: false, habilitado: true },
	{
		codigo: "maxxa_30",
		etiqueta: "Cheke Maxxa 30 días",
		diferido: true,
		habilitado: false,
		motivo: "sin_credito",
	},
];

const EMPRESA = {
	registrada: true,
	aprobada: true,
	estado: "aprobada",
	rut: "76543210-3",
	razon_social: "Santa Teresa SpA",
	medios_pago: MEDIOS,
	autenticado: true,
};

describe("estadoMediosPago", () => {
	it("sin sesión pide iniciar sesión", () => {
		expect(estadoMediosPago(200, { registrada: false, autenticado: false })).toEqual({ tipo: "invitado" });
		expect(estadoMediosPago(401, { mensaje: "x" })).toEqual({ tipo: "invitado" });
	});

	it("con sesión y sin empresa pide registrarla", () => {
		expect(estadoMediosPago(200, { registrada: false, autenticado: true })).toEqual({ tipo: "sin_empresa" });
	});

	it("una empresa aprobada muestra sus medios, tal como vienen", () => {
		const estado = estadoMediosPago(200, EMPRESA);

		expect(estado.tipo).toBe("aprobada");
		expect(estado).toMatchObject({
			empresa: { razon_social: "Santa Teresa SpA", rut: "76543210-3", medios_pago: MEDIOS },
		});
		expect(medioPreseleccionado(estado)).toBe("transferencia");
	});

	it("una empresa pendiente queda en revisión y sin ningún medio usable", () => {
		const estado = estadoMediosPago(200, { ...EMPRESA, aprobada: false, estado: "pendiente" });

		expect(estado.tipo).toBe("en_revision");
		if (estado.tipo !== "en_revision") return;
		expect(estado.empresa.medios_pago.every((m) => !m.habilitado)).toBe(true);
		expect(medioPreseleccionado(estado)).toBe("");
	});

	it("sin el campo `aprobada` falla cerrado: en revisión", () => {
		const { aprobada: _omitido, ...sinCampo } = EMPRESA;
		expect(estadoMediosPago(200, sinCampo).tipo).toBe("en_revision");
		expect(estadoMediosPago(200, { ...EMPRESA, aprobada: "true" }).tipo).toBe("en_revision");
		// El `estado` de al lado no alcanza para aprobar.
		expect(estadoMediosPago(200, { ...sinCampo, estado: "aprobada" }).tipo).toBe("en_revision");
	});

	it("aprobada y sin medios lo dice en vez de quedar vacía", () => {
		expect(estadoMediosPago(200, { ...EMPRESA, medios_pago: [] }).tipo).toBe("sin_medios");
		expect(estadoMediosPago(200, { ...EMPRESA, medios_pago: [{ foo: 1 }] }).tipo).toBe("sin_medios");
	});

	it("un medio sin `habilitado: true` no se puede elegir", () => {
		const estado = estadoMediosPago(200, {
			...EMPRESA,
			medios_pago: [
				{ codigo: "transferencia", etiqueta: "Transferencia", diferido: false, habilitado: "si" },
			],
		});
		expect(medioPreseleccionado(estado)).toBe("");
	});

	it("una respuesta fallida o con forma ajena es un error, no «sin empresa»", () => {
		expect(estadoMediosPago(503, { mensaje: "no disponible" })).toEqual({ tipo: "error" });
		expect(estadoMediosPago(200, null)).toEqual({ tipo: "error" });
		expect(estadoMediosPago(200, { algo: 1 })).toEqual({ tipo: "error" });
	});
});

describe("estadoTrasRechazoDePedido", () => {
	const aprobada = estadoMediosPago(200, EMPRESA);

	it("si la empresa volvió a revisión deja de ofrecer el botón", () => {
		const estado = estadoTrasRechazoDePedido(aprobada, 403, "PENDIENTE_APROBACION");

		expect(estado?.tipo).toBe("en_revision");
		if (estado?.tipo !== "en_revision") return;
		expect(estado.empresa.razon_social).toBe("Santa Teresa SpA");
		expect(estado.empresa.medios_pago.every((m) => !m.habilitado)).toBe(true);
	});

	it("sin empresa o sin sesión cambia al estado que corresponde", () => {
		expect(estadoTrasRechazoDePedido(aprobada, 403, "SIN_EMPRESA")).toEqual({ tipo: "sin_empresa" });
		expect(estadoTrasRechazoDePedido(aprobada, 401)).toEqual({ tipo: "invitado" });
	});

	it("cualquier otro rechazo deja el estado y solo muestra el mensaje", () => {
		expect(estadoTrasRechazoDePedido(aprobada, 422, "INSUFFICIENT_STOCK")).toBeNull();
		expect(estadoTrasRechazoDePedido(aprobada, 409)).toBeNull();
	});
});
