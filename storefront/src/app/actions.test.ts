import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * `updateCartLineQuantity` es una acción de servidor: el navegador la invoca con
 * los argumentos que quiera. Estas pruebas fijan que el precio por volumen se
 * decide con el canal que Saleor devuelve para el carrito, no con el `channel`
 * que llega del cliente. Saleor, la sesión y la App B2B van simulados: la
 * prueba no sale a la red.
 */

const CHECKOUT = "Q2hlY2tvdXQ6YWJj";
const LINEA = "Q2hlY2tvdXRMaW5lOjE=";
const USUARIO = "VXNlcjo1";

const executeAuthenticatedGraphQL = vi.fn();
const getHeaderAuthState = vi.fn();

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: vi.fn() }));
vi.mock("@/lib/auth/bff-server", () => ({ signOutSession: vi.fn() }));
vi.mock("@/lib/auth/revalidate-storefront-chrome", () => ({ revalidateStorefrontChrome: vi.fn() }));
vi.mock("@/lib/checkout", () => ({ clearCheckoutCookie: vi.fn(), detachCustomer: vi.fn() }));
vi.mock("@/lib/graphql", () => ({
	executeAuthenticatedGraphQL: (...args: unknown[]) => executeAuthenticatedGraphQL(...args),
}));
vi.mock("@/lib/auth/get-header-user", () => ({
	getHeaderAuthState: () => getHeaderAuthState(),
}));

import { updateCartLineQuantity } from "./actions";

/** Lo que contesta `checkoutLinesUpdate` para un carrito del canal indicado. */
function lineasActualizadas(canal: string) {
	return {
		ok: true,
		data: {
			checkoutLinesUpdate: {
				checkout: { id: CHECKOUT, channel: { slug: canal }, lines: [], totalPrice: null },
				errors: [],
			},
		},
	};
}

beforeEach(() => {
	process.env.B2B_APP_URL = "https://b2b.test";
	process.env.B2B_CHANNELS = "b2b-cl";
	getHeaderAuthState.mockResolvedValue({ status: "authenticated", user: { id: USUARIO } });
});

afterEach(() => {
	delete process.env.B2B_APP_URL;
	delete process.env.B2B_CHANNELS;
	executeAuthenticatedGraphQL.mockReset();
	getHeaderAuthState.mockReset();
	vi.unstubAllGlobals();
});

describe("updateCartLineQuantity", () => {
	it("un carrito retail presentado como b2b-cl no se reprecifica", async () => {
		executeAuthenticatedGraphQL.mockResolvedValue(lineasActualizadas("retail-cl"));
		const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
		vi.stubGlobal("fetch", fetchMock);

		await updateCartLineQuantity(CHECKOUT, LINEA, 12, "b2b-cl");

		expect(executeAuthenticatedGraphQL).toHaveBeenCalledTimes(1);
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it("un carrito b2b-cl se reprecifica aunque el cliente mande otro canal", async () => {
		executeAuthenticatedGraphQL.mockResolvedValue(lineasActualizadas("b2b-cl"));
		const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
		vi.stubGlobal("fetch", fetchMock);

		await updateCartLineQuantity(CHECKOUT, LINEA, 12, "retail-cl");

		expect(fetchMock).toHaveBeenCalledTimes(1);
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(url).toBe("https://b2b.test/cart/reprecio");
		expect(JSON.parse(init.body as string)).toEqual({ checkout_id: CHECKOUT, user_id: USUARIO });
	});

	it("si Saleor rechaza el cambio de cantidad no se reprecifica", async () => {
		executeAuthenticatedGraphQL.mockResolvedValue({ ok: false, error: new Error("sin stock") });
		const fetchMock = vi.fn();
		vi.stubGlobal("fetch", fetchMock);

		await updateCartLineQuantity(CHECKOUT, LINEA, 12, "b2b-cl");

		expect(fetchMock).not.toHaveBeenCalled();
	});
});
