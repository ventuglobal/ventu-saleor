import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * El contexto de retorno de Webpay viaja en una cookie httpOnly. Dos caminos
 * vuelven por el mismo `return_url`: retail (`kind:"checkout"`, cierra el checkout)
 * y B2B orden-primero (`kind:"order"`, la orden ya existe). Estas pruebas fijan el
 * ida y vuelta por `kind` y la compatibilidad con cookies viejas sin `kind`.
 *
 * `next/headers` va simulado con un almacén en memoria: write deja el valor, read
 * lo recupera; la prueba no toca la request real.
 */
const cookiesMock = vi.fn();
vi.mock("next/headers", () => ({ cookies: () => cookiesMock() }));

import {
	readWebpayContextCookie,
	WEBPAY_CTX_COOKIE,
	writeWebpayContextCookie,
	type WebpayContext,
} from "./webpay-context";

/** Almacén mínimo con la forma que usan los helpers (get().value / set / delete). */
function fakeCookieStore() {
	const store = new Map<string, string>();
	return {
		get: (name: string) => {
			const value = store.get(name);
			return value === undefined ? undefined : { value };
		},
		set: (name: string, value: string) => {
			store.set(name, value);
		},
		delete: (name: string) => {
			store.delete(name);
		},
		/** Para sembrar una cookie «cruda» (p. ej. una versión vieja). */
		seed: (name: string, value: string) => {
			store.set(name, value);
		},
	};
}

let cookieStore: ReturnType<typeof fakeCookieStore>;

beforeEach(() => {
	cookieStore = fakeCookieStore();
	cookiesMock.mockResolvedValue(cookieStore);
});

afterEach(() => {
	cookiesMock.mockReset();
});

describe("readWebpayContextCookie", () => {
	it("round-trips an order context (B2B)", async () => {
		const ctx: WebpayContext = {
			kind: "order",
			orderId: "T3JkZXI6MQ==",
			transactionId: "VHJhbnM6MQ==",
			channel: "b2b-cl",
			browseLocale: "es-cl",
		};
		await writeWebpayContextCookie(ctx);

		expect(await readWebpayContextCookie()).toEqual(ctx);
	});

	it("round-trips a checkout context (retail)", async () => {
		const ctx: WebpayContext = {
			kind: "checkout",
			checkoutId: "Q2hlY2tvdXQ6MQ==",
			transactionId: "VHJhbnM6Mg==",
			channel: "retail-cl",
		};
		await writeWebpayContextCookie(ctx);

		expect(await readWebpayContextCookie()).toEqual(ctx);
	});

	it("reads a legacy cookie without `kind` as checkout", async () => {
		cookieStore.seed(
			WEBPAY_CTX_COOKIE,
			JSON.stringify({ checkoutId: "Q2hlY2tvdXQ6OQ==", transactionId: "VHJhbnM6OQ==", channel: "retail-cl" }),
		);

		expect(await readWebpayContextCookie()).toEqual({
			kind: "checkout",
			checkoutId: "Q2hlY2tvdXQ6OQ==",
			transactionId: "VHJhbnM6OQ==",
			channel: "retail-cl",
			browseLocale: undefined,
		});
	});

	it("rejects an order context missing orderId", async () => {
		cookieStore.seed(
			WEBPAY_CTX_COOKIE,
			JSON.stringify({ kind: "order", transactionId: "VHJhbnM6MQ==", channel: "b2b-cl" }),
		);

		expect(await readWebpayContextCookie()).toBeNull();
	});

	it("rejects a context missing transactionId or channel", async () => {
		cookieStore.seed(WEBPAY_CTX_COOKIE, JSON.stringify({ kind: "order", orderId: "T3JkZXI6MQ==" }));
		expect(await readWebpayContextCookie()).toBeNull();
	});

	it("returns null when the cookie is absent or corrupt", async () => {
		expect(await readWebpayContextCookie()).toBeNull();

		cookieStore.seed(WEBPAY_CTX_COOKIE, "{not json");
		expect(await readWebpayContextCookie()).toBeNull();
	});
});
