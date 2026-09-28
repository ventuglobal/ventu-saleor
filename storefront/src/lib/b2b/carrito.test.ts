import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getHeaderAuthState = vi.fn();

vi.mock("@/lib/auth/get-header-user", () => ({
	getHeaderAuthState: () => getHeaderAuthState(),
}));

import { reprecificar } from "./carrito";

const CHECKOUT = "Q2hlY2tvdXQ6YWJj";
const USUARIO = "VXNlcjo1";

function respuesta(body: unknown, status = 200) {
	return vi.fn().mockResolvedValue({ ok: status >= 200 && status < 300, status, json: async () => body });
}

beforeEach(() => {
	process.env.B2B_APP_URL = "https://b2b.test";
	process.env.B2B_CHANNELS = "b2b-cl";
	getHeaderAuthState.mockResolvedValue({ status: "authenticated", user: { id: USUARIO } });
});

afterEach(() => {
	delete process.env.B2B_APP_URL;
	delete process.env.B2B_CHANNELS;
	delete process.env.B2B_APP_TOKEN;
	getHeaderAuthState.mockReset();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe("reprecificar", () => {
	it("se autentica ante la App B2B con el token de servicio", async () => {
		process.env.B2B_APP_TOKEN = "token-de-prueba";
		const fetchMock = respuesta({ aplicado: true });
		vi.stubGlobal("fetch", fetchMock);

		await reprecificar(CHECKOUT, "b2b-cl");

		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(url).toBe("https://b2b.test/cart/reprecio");
		expect(init.headers).toEqual({
			"Content-Type": "application/json",
			Authorization: "Bearer token-de-prueba",
		});
	});

	it("en retail no llama a la App B2B", async () => {
		const fetchMock = respuesta({ aplicado: true });
		vi.stubGlobal("fetch", fetchMock);

		await reprecificar(CHECKOUT, "retail-cl");

		expect(fetchMock).not.toHaveBeenCalled();
	});

	it("sin el canal del carrito según Saleor no llama a la App B2B", async () => {
		// La mutación de líneas falló o no devolvió el carrito: no se sabe en
		// qué canal está, y adivinarlo podría aplicar tramos a un carrito retail.
		const fetchMock = respuesta({ aplicado: true });
		vi.stubGlobal("fetch", fetchMock);

		await reprecificar(CHECKOUT, null);
		await reprecificar(CHECKOUT, undefined);

		expect(fetchMock).not.toHaveBeenCalled();
	});

	it("un rechazo de la App B2B se registra y no rompe el carrito", async () => {
		const error = vi.spyOn(console, "error").mockImplementation(() => {});
		vi.stubGlobal("fetch", respuesta({ detail: "checkout inexistente" }, 422));

		await expect(reprecificar(CHECKOUT, "b2b-cl")).resolves.toBeUndefined();
		expect(error).toHaveBeenCalledWith(expect.stringContaining("422"), "checkout inexistente");
	});
});
