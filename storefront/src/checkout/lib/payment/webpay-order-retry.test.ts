import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
	clearWebpayOrderPending,
	isWebpayOrderPendingInSession,
	markWebpayOrderPending,
} from "./webpay-order-retry";

/**
 * La marca de reintento vive en `sessionStorage` y acota el ofrecimiento a la
 * misma sesión que creó la orden. En el runner (node) no hay `window`, así que se
 * stubea un `sessionStorage` en memoria; sin él, los helpers deben degradar a
 * «sin reintento» sin romper (modo privado / storage bloqueado).
 */
function fakeSessionStorage() {
	const store = new Map<string, string>();
	return {
		getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
		setItem: (k: string, v: string) => void store.set(k, v),
		removeItem: (k: string) => void store.delete(k),
	};
}

const ORDER = "T3JkZXI6MQ==";
const OTRA = "T3JkZXI6Mg==";

afterEach(() => {
	vi.unstubAllGlobals();
});

describe("webpay-order-retry (con sessionStorage)", () => {
	beforeEach(() => {
		vi.stubGlobal("window", { sessionStorage: fakeSessionStorage() });
	});

	it("marca y detecta la orden pendiente de esta sesión", () => {
		expect(isWebpayOrderPendingInSession(ORDER)).toBe(false);
		markWebpayOrderPending(ORDER);
		expect(isWebpayOrderPendingInSession(ORDER)).toBe(true);
	});

	it("solo reconoce la orden marcada, no otra", () => {
		markWebpayOrderPending(ORDER);
		expect(isWebpayOrderPendingInSession(OTRA)).toBe(false);
	});

	it("limpia solo si coincide la orden", () => {
		markWebpayOrderPending(ORDER);
		clearWebpayOrderPending(OTRA);
		expect(isWebpayOrderPendingInSession(ORDER)).toBe(true);
		clearWebpayOrderPending(ORDER);
		expect(isWebpayOrderPendingInSession(ORDER)).toBe(false);
	});
});

describe("webpay-order-retry (sin storage disponible)", () => {
	it("degrada a «sin reintento» sin lanzar", () => {
		// window ausente ⇒ cada acceso tira y se traga el error.
		expect(() => markWebpayOrderPending(ORDER)).not.toThrow();
		expect(isWebpayOrderPendingInSession(ORDER)).toBe(false);
		expect(() => clearWebpayOrderPending(ORDER)).not.toThrow();
	});
});
