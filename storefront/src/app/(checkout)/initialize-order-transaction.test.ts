import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * `initializeOrderTransaction` es la server action orden-primero (B2B): el
 * navegador le pasa un `orderId`, y ella —no el cliente— resuelve canal y monto
 * desde la orden en el servidor. Estas pruebas fijan el borde de seguridad:
 *
 *  - Webpay solo se inicializa si el canal de la orden está en `WEBPAY_CHANNELS`.
 *  - El monto sale del total de la orden; nunca se confía en un valor del cliente.
 *
 * Saleor, la orden y las traducciones van simulados: la prueba no sale a la red.
 * Los guards de Webpay son los REALES (puros, por env), que es lo que se valida.
 */
const executeAuthenticatedGraphQL = vi.fn();
const fetchOrderOnServer = vi.fn();

vi.mock("next/headers", () => ({ cookies: vi.fn() }));
vi.mock("next/server", () => ({ after: vi.fn() }));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn(), revalidateTag: vi.fn() }));
vi.mock("@/app/actions", () => ({ saveCheckoutId: vi.fn() }));
vi.mock("@/lib/checkout", () => ({ clearCheckoutCookie: vi.fn(), detachCustomer: vi.fn() }));
vi.mock("@/lib/graphql", () => ({
	executeAuthenticatedGraphQL: (...args: unknown[]) => executeAuthenticatedGraphQL(...args),
	executePublicGraphQL: vi.fn(),
	executeRawGraphQL: vi.fn(),
}));
vi.mock("@/checkout/lib/server/fetch-order", () => ({
	fetchOrderOnServer: (...args: unknown[]) => fetchOrderOnServer(...args),
}));
vi.mock("@/checkout/lib/server/get-checkout-server-translations", () => ({
	getCheckoutServerTranslations: async () => ({ server: (key: string) => key }),
}));

import { initializeOrderTransaction } from "./actions";

const WEBPAY = { id: "cl.ventu.pagos", data: {} };
const ORDER_ID = "T3JkZXI6MQ==";

/** Una orden con el canal y total dados, con la forma que lee la action. */
function orden(channel: string, amount = 19990) {
	return { id: ORDER_ID, channel: { slug: channel }, total: { gross: { amount } } };
}

function initializeOk() {
	return {
		ok: true,
		data: {
			transactionInitialize: {
				transaction: { id: "VHJhbnM6MQ==" },
				data: { webpayUrl: "https://wp/x", token: "TOK1" },
				errors: [],
			},
		},
	};
}

beforeEach(() => {
	process.env.WEBPAY_CHANNELS = "retail-cl,b2b-cl";
});

afterEach(() => {
	delete process.env.WEBPAY_CHANNELS;
	executeAuthenticatedGraphQL.mockReset();
	fetchOrderOnServer.mockReset();
});

describe("initializeOrderTransaction (borde de canal order-aware)", () => {
	it("inicializa Webpay para una orden b2b-cl (canal permitido)", async () => {
		fetchOrderOnServer.mockResolvedValue(orden("b2b-cl"));
		executeAuthenticatedGraphQL.mockResolvedValue(initializeOk());

		const res = await initializeOrderTransaction(ORDER_ID, WEBPAY);

		expect(res.ok).toBe(true);
		// El monto va desde el total de la orden, no del cliente.
		expect(executeAuthenticatedGraphQL).toHaveBeenCalledTimes(1);
		const call = executeAuthenticatedGraphQL.mock.calls[0][1];
		expect(call.variables).toMatchObject({ checkoutId: ORDER_ID, amount: 19990, paymentGateway: WEBPAY });
	});

	it("inicializa Webpay para retail-cl (canal permitido)", async () => {
		fetchOrderOnServer.mockResolvedValue(orden("retail-cl"));
		executeAuthenticatedGraphQL.mockResolvedValue(initializeOk());

		const res = await initializeOrderTransaction(ORDER_ID, WEBPAY);

		expect(res.ok).toBe(true);
	});

	it("rechaza Webpay para un canal fuera de la lista y NO llama a Saleor", async () => {
		process.env.WEBPAY_CHANNELS = "retail-cl";
		fetchOrderOnServer.mockResolvedValue(orden("b2b-cl"));

		const res = await initializeOrderTransaction(ORDER_ID, WEBPAY);

		expect(res.ok).toBe(false);
		expect(executeAuthenticatedGraphQL).not.toHaveBeenCalled();
	});

	it("falla si la orden no existe", async () => {
		fetchOrderOnServer.mockResolvedValue(null);

		const res = await initializeOrderTransaction(ORDER_ID, WEBPAY);

		expect(res.ok).toBe(false);
		expect(executeAuthenticatedGraphQL).not.toHaveBeenCalled();
	});

	it("falla si el total de la orden no es un monto válido", async () => {
		fetchOrderOnServer.mockResolvedValue(orden("b2b-cl", 0));

		const res = await initializeOrderTransaction(ORDER_ID, WEBPAY);

		expect(res.ok).toBe(false);
		expect(executeAuthenticatedGraphQL).not.toHaveBeenCalled();
	});
});
