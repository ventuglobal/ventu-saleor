import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getEmpresa, registrarEmpresa } from "./company";
import { esCanalB2B } from "./canales";

const USUARIO = "VXNlcjo1";

const EMPRESA = {
	registrada: true,
	rut: "76543210-3",
	razon_social: "Comercial Santa Teresa SpA",
	nivel_precio: "b2b-cl",
	condicion_pago: "contado",
	credito_estado: "sin_solicitud",
	medios_pago: [{ codigo: "transferencia", etiqueta: "Transferencia", diferido: true, habilitado: true }],
};

function respuesta(body: unknown, ok = true, status = ok ? 200 : 422) {
	return vi.fn().mockResolvedValue({ ok, status, json: async () => body });
}

beforeEach(() => {
	process.env.B2B_APP_URL = "https://b2b.test";
});

afterEach(() => {
	delete process.env.B2B_APP_URL;
	delete process.env.B2B_CHANNELS;
	vi.unstubAllGlobals();
});

describe("getEmpresa", () => {
	it("devuelve la empresa del usuario", async () => {
		vi.stubGlobal("fetch", respuesta(EMPRESA));
		await expect(getEmpresa(USUARIO)).resolves.toEqual(EMPRESA);
	});

	it("un usuario sin empresa no es un error", async () => {
		vi.stubGlobal("fetch", respuesta({ registrada: false }));
		await expect(getEmpresa(USUARIO)).resolves.toEqual({ registrada: false });
	});

	it("sin sesión no se consulta", async () => {
		const fetchMock = respuesta(EMPRESA);
		vi.stubGlobal("fetch", fetchMock);

		await expect(getEmpresa(null)).resolves.toEqual({ registrada: false });
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it("una App B2B caída no bloquea la tienda", async () => {
		vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));
		await expect(getEmpresa(USUARIO)).resolves.toEqual({ registrada: false });
	});

	it("una respuesta de forma ajena se descarta", async () => {
		vi.stubGlobal("fetch", respuesta({ registrada: true }));
		await expect(getEmpresa(USUARIO)).resolves.toEqual({ registrada: false });
	});
});

describe("registrarEmpresa", () => {
	it("da de alta la empresa con el id del servidor", async () => {
		const fetchMock = respuesta({ rut: "76543210-3" });
		vi.stubGlobal("fetch", fetchMock);

		const r = await registrarEmpresa(USUARIO, { rut: "76.543.210-3", razonSocial: "Santa Teresa" });

		expect(r).toEqual({ ok: true, rut: "76543210-3" });
		const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(JSON.parse(String(init.body))).toMatchObject({ user_id: USUARIO, rut: "76.543.210-3" });
	});

	it("propaga el motivo del rechazo", async () => {
		// El texto de la App B2B —dígito verificador, RUT ya registrado— le sirve
		// a quien se está registrando; uno genérico no.
		vi.stubGlobal("fetch", respuesta({ detail: "dígito verificador incorrecto" }, false));

		const r = await registrarEmpresa(USUARIO, { rut: "76.543.210-4", razonSocial: "Santa Teresa" });

		expect(r).toEqual({ ok: false, status: 422, mensaje: "dígito verificador incorrecto" });
	});

	it("sin App B2B configurada el alta falla explícitamente", async () => {
		delete process.env.B2B_APP_URL;
		const r = await registrarEmpresa(USUARIO, { rut: "1-9", razonSocial: "X" });
		expect(r.ok).toBe(false);
	});
});

describe("esCanalB2B", () => {
	it("sin configurar, ningún canal exige empresa", () => {
		expect(esCanalB2B("b2b-cl")).toBe(false);
	});

	it("reconoce los canales configurados", () => {
		process.env.B2B_CHANNELS = "b2b-cl, mayorista";
		expect(esCanalB2B("b2b-cl")).toBe(true);
		expect(esCanalB2B("mayorista")).toBe(true);
		expect(esCanalB2B("retail-cl")).toBe(false);
	});
});
