import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { b2bHeaders, getEmpresa, registrarEmpresa } from "./company";
import { esCanalB2B } from "./canales";
import { MENSAJE_ALTA_NO_DISPONIBLE, MENSAJE_RUT_INVALIDO } from "./errores";

const USUARIO = "VXNlcjo1";

const EMPRESA = {
	registrada: true,
	aprobada: true,
	estado: "aprobada",
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
	delete process.env.B2B_APP_TOKEN;
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe("b2bHeaders", () => {
	it("con token agrega la autorización Bearer", () => {
		process.env.B2B_APP_TOKEN = "token-de-prueba";
		expect(b2bHeaders()).toEqual({ Authorization: "Bearer token-de-prueba" });
	});

	it("sin token no agrega cabecera de autorización", () => {
		expect(b2bHeaders()).toEqual({});
		expect(b2bHeaders({ "Content-Type": "application/json" })).toEqual({
			"Content-Type": "application/json",
		});
	});

	it("un token en blanco cuenta como ausente", () => {
		// `Bearer ` a secas lo rechazaría la App B2B igual, pero con un 401 que
		// confunde más que la ausencia de cabecera.
		process.env.B2B_APP_TOKEN = "   ";
		expect(b2bHeaders()).toEqual({});
	});

	it("conserva las cabeceras extra y no deja que pisen la autorización", () => {
		process.env.B2B_APP_TOKEN = "token-de-prueba";
		expect(b2bHeaders({ "Content-Type": "application/json", Authorization: "Bearer otro" })).toEqual({
			"Content-Type": "application/json",
			Authorization: "Bearer token-de-prueba",
		});
	});
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

	it("una App B2B caída no bloquea la tienda, pero se distingue de «sin empresa»", async () => {
		vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));
		await expect(getEmpresa(USUARIO)).resolves.toEqual({ registrada: false, error: true });
	});

	it("un error de la App B2B tampoco cuenta como «sin empresa»", async () => {
		vi.stubGlobal("fetch", respuesta({ detail: "falla" }, false, 502));
		await expect(getEmpresa(USUARIO)).resolves.toEqual({ registrada: false, error: true });
	});

	it("una respuesta de forma ajena se descarta", async () => {
		vi.stubGlobal("fetch", respuesta({ registrada: true }));
		await expect(getEmpresa(USUARIO)).resolves.toEqual({ registrada: false, error: true });
	});

	it("una empresa en revisión no tiene medios habilitados", async () => {
		vi.stubGlobal(
			"fetch",
			respuesta({
				...EMPRESA,
				aprobada: false,
				estado: "pendiente",
				medios_pago: [
					{
						codigo: "transferencia",
						etiqueta: "Transferencia",
						diferido: true,
						habilitado: false,
						motivo: "pendiente_aprobacion",
					},
				],
			}),
		);

		const r = await getEmpresa(USUARIO);

		expect(r).toMatchObject({ registrada: true, aprobada: false, estado: "pendiente" });
	});

	it("sin el campo `aprobada` la empresa queda en revisión (falla cerrada)", async () => {
		// Una App B2B anterior a la aprobación manda los medios habilitados y no
		// dice nada de la aprobación: leerla como aprobada abriría los pedidos.
		const { aprobada: _a, estado: _e, ...anterior } = EMPRESA;
		vi.stubGlobal("fetch", respuesta(anterior));

		const r = await getEmpresa(USUARIO);

		expect(r).toMatchObject({ registrada: true, aprobada: false, estado: "pendiente" });
		expect(
			r.registrada && r.medios_pago.every((m) => !m.habilitado && m.motivo === "pendiente_aprobacion"),
		).toBe(true);
	});

	it("un `estado` que contradice a `aprobada` no la aprueba", async () => {
		vi.stubGlobal("fetch", respuesta({ ...EMPRESA, aprobada: "si", estado: "aprobada" }));
		await expect(getEmpresa(USUARIO)).resolves.toMatchObject({ aprobada: false, estado: "pendiente" });
	});

	it("manda el token de servicio cuando está configurado", async () => {
		process.env.B2B_APP_TOKEN = "token-de-prueba";
		const fetchMock = respuesta(EMPRESA);
		vi.stubGlobal("fetch", fetchMock);

		await getEmpresa(USUARIO);

		const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(init.headers).toEqual({ Authorization: "Bearer token-de-prueba" });
	});

	it("sin token consulta sin cabecera de autorización", async () => {
		const fetchMock = respuesta(EMPRESA);
		vi.stubGlobal("fetch", fetchMock);

		await getEmpresa(USUARIO);

		const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(init.headers).not.toHaveProperty("Authorization");
	});

	it("un 401 se registra como problema de configuración del token", async () => {
		const error = vi.spyOn(console, "error").mockImplementation(() => {});
		vi.stubGlobal("fetch", respuesta({ detail: "no autorizado" }, false, 401));

		await expect(getEmpresa(USUARIO)).resolves.toEqual({ registrada: false, error: true });
		expect(error).toHaveBeenCalledWith(expect.stringContaining("B2B_APP_TOKEN"));
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

	it("traduce el motivo del rechazo y deja el texto crudo en el log", async () => {
		// El texto de la App B2B repite el RUT y el cálculo del verificador: sirve
		// en el log, no en pantalla.
		const aviso = vi.spyOn(console, "warn").mockImplementation(() => {});
		const crudo = "dígito verificador incorrecto en '76.543.210-4': es 4, debería ser 3";
		vi.stubGlobal("fetch", respuesta({ detail: crudo }, false));

		const r = await registrarEmpresa(USUARIO, { rut: "76.543.210-4", razonSocial: "Santa Teresa" });

		expect(r).toEqual({ ok: false, status: 422, mensaje: MENSAJE_RUT_INVALIDO, code: "RUT_INVALIDO" });
		expect(JSON.stringify(r)).not.toContain("debería");
		expect(aviso).toHaveBeenCalledWith(
			expect.stringContaining("422"),
			expect.stringContaining("debería ser 3"),
		);
	});

	it("manda el token de servicio junto con el tipo de contenido", async () => {
		process.env.B2B_APP_TOKEN = "token-de-prueba";
		const fetchMock = respuesta({ rut: "76543210-3" });
		vi.stubGlobal("fetch", fetchMock);

		await registrarEmpresa(USUARIO, { rut: "76.543.210-3", razonSocial: "Santa Teresa" });

		const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(init.headers).toEqual({
			"Content-Type": "application/json",
			Authorization: "Bearer token-de-prueba",
		});
	});

	it("un usuario que ya tiene empresa recibe un mensaje propio, distinto del RUT ya registrado", async () => {
		vi.spyOn(console, "warn").mockImplementation(() => {});
		vi.stubGlobal(
			"fetch",
			respuesta(
				{ detail: "el usuario ya tiene una empresa registrada; los cambios los hace el equipo de Ventu" },
				false,
				409,
			),
		);
		const propia = await registrarEmpresa(USUARIO, { rut: "76.543.210-3", razonSocial: "Santa Teresa" });

		vi.stubGlobal("fetch", respuesta({ detail: "el RUT 76543210-3 ya está registrado" }, false, 409));
		const ajena = await registrarEmpresa(USUARIO, { rut: "76.543.210-3", razonSocial: "Santa Teresa" });

		expect(propia).toMatchObject({
			ok: false,
			status: 409,
			mensaje: expect.stringContaining("Tu cuenta ya tiene"),
		});
		expect(ajena).toMatchObject({ ok: false, status: 409, mensaje: expect.stringContaining("otra cuenta") });
	});

	it("un token rechazado no se le muestra al comprador como «no autorizado»", async () => {
		vi.spyOn(console, "error").mockImplementation(() => {});
		vi.stubGlobal("fetch", respuesta({ detail: "token inválido" }, false, 401));

		const r = await registrarEmpresa(USUARIO, { rut: "76.543.210-3", razonSocial: "Santa Teresa" });

		expect(r).toEqual({ ok: false, status: 503, mensaje: MENSAJE_ALTA_NO_DISPONIBLE });
	});

	it("una App B2B caída responde el mensaje de no disponible", async () => {
		vi.spyOn(console, "error").mockImplementation(() => {});
		vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));

		const r = await registrarEmpresa(USUARIO, { rut: "76.543.210-3", razonSocial: "Santa Teresa" });

		expect(r).toEqual({ ok: false, status: 503, mensaje: MENSAJE_ALTA_NO_DISPONIBLE });
	});

	it("sin App B2B configurada el alta falla explícitamente", async () => {
		vi.spyOn(console, "error").mockImplementation(() => {});
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
