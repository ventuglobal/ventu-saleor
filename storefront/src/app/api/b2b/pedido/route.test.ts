import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

/**
 * La ruta que cierra el carrito como pedido por pagar. Todo lo externo va
 * simulado —sesión, cookies del carrito y la App B2B—: la prueba no sale a la
 * red.
 */

const USUARIO = "VXNlcjo1";
const CHECKOUT = "Q2hlY2tvdXQ6YWJj";

const getHeaderAuthState = vi.fn();
const getIdFromCookies = vi.fn();
const clearCheckoutCookie = vi.fn();

vi.mock("@/lib/auth/get-header-user", () => ({
	getHeaderAuthState: () => getHeaderAuthState(),
}));

vi.mock("@/lib/checkout", () => ({
	getIdFromCookies: (canal: string) => getIdFromCookies(canal),
	clearCheckoutCookie: (canal: string) => clearCheckoutCookie(canal),
}));

import { CODIGO_EN_REVISION, EMPRESA_EN_REVISION } from "@/lib/b2b/errores";

import { POST } from "./route";

function pedir(cuerpo: unknown) {
	return POST(
		new NextRequest("http://localhost/api/b2b/pedido", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(cuerpo),
		}),
	);
}

function respuesta(body: unknown, status = 200) {
	return vi.fn().mockResolvedValue({ ok: status >= 200 && status < 300, status, json: async () => body });
}

const PEDIDO = {
	order_id: "T3JkZXI6MQ==",
	numero: "1042",
	estado: "UNCONFIRMED",
	total: 120000,
	moneda: "CLP",
	metodo_pago: "transferencia",
};

beforeEach(() => {
	process.env.B2B_APP_URL = "https://b2b.test";
	process.env.B2B_CHANNELS = "b2b-cl";
	getHeaderAuthState.mockResolvedValue({ status: "authenticated", user: { id: USUARIO } });
	getIdFromCookies.mockResolvedValue(CHECKOUT);
	clearCheckoutCookie.mockResolvedValue(undefined);
});

afterEach(() => {
	delete process.env.B2B_APP_URL;
	delete process.env.B2B_CHANNELS;
	delete process.env.B2B_APP_TOKEN;
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	getHeaderAuthState.mockReset();
	getIdFromCookies.mockReset();
	clearCheckoutCookie.mockReset();
});

describe("POST /api/b2b/pedido", () => {
	it("en un canal que no es de empresa responde 403 y no toca la App B2B", async () => {
		const fetchMock = respuesta(PEDIDO);
		vi.stubGlobal("fetch", fetchMock);

		const res = await pedir({ canal: "retail-cl", metodoPago: "transferencia" });

		expect(res.status).toBe(403);
		await expect(res.json()).resolves.toEqual({ mensaje: "Este canal no admite pedidos de empresa." });
		expect(fetchMock).not.toHaveBeenCalled();
		expect(getIdFromCookies).not.toHaveBeenCalled();
	});

	it("sin canales de empresa configurados, ningún canal admite el pedido", async () => {
		delete process.env.B2B_CHANNELS;
		const fetchMock = respuesta(PEDIDO);
		vi.stubGlobal("fetch", fetchMock);

		const res = await pedir({ canal: "b2b-cl", metodoPago: "transferencia" });

		expect(res.status).toBe(403);
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it("en un canal de empresa crea el pedido con el carrito de la cookie y el usuario de la sesión", async () => {
		process.env.B2B_APP_TOKEN = "token-de-prueba";
		const fetchMock = respuesta({ ...PEDIDO, instrucciones_pago: "Banco Estado\nCta. 123" });
		vi.stubGlobal("fetch", fetchMock);

		const res = await pedir({ canal: "b2b-cl", metodoPago: "transferencia" });

		expect(res.status).toBe(200);
		await expect(res.json()).resolves.toEqual({ ...PEDIDO, instrucciones_pago: "Banco Estado\nCta. 123" });

		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(url).toBe("https://b2b.test/pedido");
		expect(init.headers).toEqual({
			"Content-Type": "application/json",
			Authorization: "Bearer token-de-prueba",
		});
		expect(JSON.parse(String(init.body))).toEqual({
			checkout_id: CHECKOUT,
			user_id: USUARIO,
			metodo_pago: "transferencia",
		});
		expect(getIdFromCookies).toHaveBeenCalledWith("b2b-cl");
		expect(clearCheckoutCookie).toHaveBeenCalledWith("b2b-cl");
	});

	it("sin instrucciones de pago responde null, para que la confirmación use su mensaje de siempre", async () => {
		vi.stubGlobal("fetch", respuesta(PEDIDO));

		const res = await pedir({ canal: "b2b-cl", metodoPago: "maxxa_30" });

		await expect(res.json()).resolves.toMatchObject({ instrucciones_pago: null });
	});

	it("unas instrucciones con forma ajena se descartan", async () => {
		vi.stubGlobal("fetch", respuesta({ ...PEDIDO, instrucciones_pago: { html: "<b>x</b>" } }));

		const res = await pedir({ canal: "b2b-cl", metodoPago: "transferencia" });

		await expect(res.json()).resolves.toMatchObject({ instrucciones_pago: null });
	});

	it("traduce el rechazo de Saleor y deja el texto crudo solo en el log", async () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const crudo =
			"[{'field': 'lines', 'message': 'Insufficient product stock', 'code': 'INSUFFICIENT_STOCK'}]";
		vi.stubGlobal("fetch", respuesta({ detail: crudo }, 422));

		const res = await pedir({ canal: "b2b-cl", metodoPago: "transferencia" });

		expect(res.status).toBe(422);
		const cuerpo = (await res.json()) as { mensaje: string; code?: string };
		expect(cuerpo.code).toBe("INSUFFICIENT_STOCK");
		expect(cuerpo.mensaje).toMatch(/stock suficiente/);
		expect(JSON.stringify(cuerpo)).not.toContain("Insufficient");
		expect(JSON.stringify(warn.mock.calls)).toContain("Insufficient product stock");
		expect(clearCheckoutCookie).not.toHaveBeenCalled();
	});

	it("usa el `code` que manda la App B2B, también anidado en `detail`", async () => {
		vi.spyOn(console, "warn").mockImplementation(() => {});
		vi.stubGlobal("fetch", respuesta({ detail: { detail: "sin líneas", code: "NO_LINES" } }, 422));

		const res = await pedir({ canal: "b2b-cl", metodoPago: "transferencia" });

		expect(res.status).toBe(422);
		await expect(res.json()).resolves.toMatchObject({
			code: "NO_LINES",
			mensaje: expect.stringMatching(/vacío/),
		});
	});

	it("una empresa en revisión recibe el 403 con su código, para que el checkout cambie de estado", async () => {
		vi.spyOn(console, "warn").mockImplementation(() => {});
		vi.stubGlobal("fetch", respuesta({ detail: EMPRESA_EN_REVISION, code: "PENDIENTE_APROBACION" }, 403));

		const res = await pedir({ canal: "b2b-cl", metodoPago: "transferencia" });

		expect(res.status).toBe(403);
		await expect(res.json()).resolves.toEqual({ mensaje: EMPRESA_EN_REVISION, code: CODIGO_EN_REVISION });
	});

	it("un medio no disponible no reenvía el motivo interno", async () => {
		vi.spyOn(console, "warn").mockImplementation(() => {});
		vi.stubGlobal("fetch", respuesta({ detail: "el medio 'maxxa_30' todavía no está conectado" }, 409));

		const res = await pedir({ canal: "b2b-cl", metodoPago: "maxxa_30" });

		expect(res.status).toBe(409);
		const { mensaje } = (await res.json()) as { mensaje: string };
		expect(mensaje).toMatch(/medio de pago/);
		expect(mensaje).not.toContain("maxxa");
	});

	it("un error sin forma conocida cae al mensaje genérico", async () => {
		vi.spyOn(console, "warn").mockImplementation(() => {});
		vi.stubGlobal("fetch", respuesta("Internal Server Error", 500));

		const res = await pedir({ canal: "b2b-cl", metodoPago: "transferencia" });

		expect(res.status).toBe(500);
		await expect(res.json()).resolves.toEqual({
			mensaje: "No pudimos crear el pedido. Intenta de nuevo en unos minutos.",
		});
	});

	it("un token rechazado se presenta como servicio no disponible", async () => {
		vi.spyOn(console, "error").mockImplementation(() => {});
		vi.stubGlobal("fetch", respuesta({ detail: "token inválido" }, 401));

		const res = await pedir({ canal: "b2b-cl", metodoPago: "transferencia" });

		expect(res.status).toBe(503);
		expect(clearCheckoutCookie).not.toHaveBeenCalled();
	});

	it("si la App B2B no contesta a tiempo pide revisar los pedidos antes de reintentar", async () => {
		vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("tardó", "TimeoutError")));

		const res = await pedir({ canal: "b2b-cl", metodoPago: "transferencia" });

		expect(res.status).toBe(504);
		const { mensaje } = (await res.json()) as { mensaje: string };
		expect(mensaje).toContain("Mis pedidos");
	});

	it("sin sesión no crea pedido", async () => {
		getHeaderAuthState.mockResolvedValue({ status: "guest" });
		const fetchMock = respuesta(PEDIDO);
		vi.stubGlobal("fetch", fetchMock);

		const res = await pedir({ canal: "b2b-cl", metodoPago: "transferencia" });

		expect(res.status).toBe(401);
		expect(fetchMock).not.toHaveBeenCalled();
	});
});
