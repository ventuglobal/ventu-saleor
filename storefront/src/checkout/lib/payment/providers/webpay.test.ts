import { afterEach, describe, expect, it, vi } from "vitest";
import {
	findWebpayGateway,
	getWebpayChannelGuardError,
	getWebpayPaymentGuardError,
	getWebpayTransactionError,
	isWebpayChargeSuccess,
	isWebpayGateway,
	isWebpayPaymentEnabled,
	parseWebpayRedirect,
	WEBPAY_GATEWAY_ID,
} from "./webpay";

describe("isWebpayGateway", () => {
	it("matches the ventu-pagos app id", () => {
		expect(isWebpayGateway(WEBPAY_GATEWAY_ID)).toBe(true);
		expect(isWebpayGateway("cl.ventu.pagos")).toBe(true);
	});

	it("does not match other gateway ids", () => {
		expect(isWebpayGateway("saleor.io.stripe")).toBe(false);
		expect(isWebpayGateway("webpay")).toBe(false);
	});
});

describe("findWebpayGateway", () => {
	it("returns the webpay gateway from checkout gateways", () => {
		const webpay = { id: WEBPAY_GATEWAY_ID, name: "Webpay" };
		expect(findWebpayGateway([{ id: "saleor.io.stripe", name: "Stripe" }, webpay])).toEqual(webpay);
	});

	it("returns undefined when absent", () => {
		expect(findWebpayGateway([{ id: "saleor.io.stripe", name: "Stripe" }])).toBeUndefined();
		expect(findWebpayGateway(null)).toBeUndefined();
	});
});

describe("isWebpayPaymentEnabled", () => {
	afterEach(() => {
		vi.unstubAllEnvs();
	});

	it("is on by default (retail medium of payment)", () => {
		expect(isWebpayPaymentEnabled()).toBe(true);
	});

	it("can be turned off via the public flag", () => {
		vi.stubEnv("NEXT_PUBLIC_ENABLE_WEBPAY_PAYMENTS", "false");
		expect(isWebpayPaymentEnabled()).toBe(false);
	});

	it("can be turned off server-side", () => {
		vi.stubEnv("ENABLE_WEBPAY_PAYMENTS", "false");
		expect(isWebpayPaymentEnabled()).toBe(false);
	});
});

describe("getWebpayPaymentGuardError", () => {
	afterEach(() => {
		vi.unstubAllEnvs();
	});

	it("ignores non-webpay gateways", () => {
		expect(getWebpayPaymentGuardError("saleor.io.stripe")).toBeNull();
		expect(getWebpayPaymentGuardError(null)).toBeNull();
	});

	it("passes when enabled", () => {
		expect(getWebpayPaymentGuardError(WEBPAY_GATEWAY_ID)).toBeNull();
	});

	it("blocks when disabled", () => {
		vi.stubEnv("NEXT_PUBLIC_ENABLE_WEBPAY_PAYMENTS", "false");
		expect(getWebpayPaymentGuardError(WEBPAY_GATEWAY_ID)).not.toBeNull();
	});
});

describe("getWebpayChannelGuardError (security boundary)", () => {
	afterEach(() => {
		vi.unstubAllEnvs();
	});

	it("ignores non-webpay gateways", () => {
		expect(getWebpayChannelGuardError("saleor.io.stripe", "b2b-cl")).toBeNull();
	});

	it("allows the configured retail channel (default)", () => {
		expect(getWebpayChannelGuardError(WEBPAY_GATEWAY_ID, "retail-cl")).toBeNull();
	});

	it("rejects a channel outside WEBPAY_CHANNELS", () => {
		expect(getWebpayChannelGuardError(WEBPAY_GATEWAY_ID, "b2b-cl")).not.toBeNull();
		expect(getWebpayChannelGuardError(WEBPAY_GATEWAY_ID, null)).not.toBeNull();
	});

	it("honours a custom channel list", () => {
		vi.stubEnv("WEBPAY_CHANNELS", "retail-cl,retail-ar");
		expect(getWebpayChannelGuardError(WEBPAY_GATEWAY_ID, "retail-ar")).toBeNull();
		expect(getWebpayChannelGuardError(WEBPAY_GATEWAY_ID, "retail-cl")).toBeNull();
		expect(getWebpayChannelGuardError(WEBPAY_GATEWAY_ID, "retail-br")).not.toBeNull();
	});
});

describe("parseWebpayRedirect", () => {
	it("reads webpayUrl + token from transaction data", () => {
		expect(parseWebpayRedirect({ webpayUrl: "https://wp/x", token: "TOK1" })).toEqual({
			webpayUrl: "https://wp/x",
			token: "TOK1",
		});
	});

	it("returns null when missing or malformed", () => {
		expect(parseWebpayRedirect(null)).toBeNull();
		expect(parseWebpayRedirect({ webpayUrl: "https://wp/x" })).toBeNull();
		expect(parseWebpayRedirect({ token: "TOK1" })).toBeNull();
		expect(parseWebpayRedirect({ webpayUrl: "", token: "TOK1" })).toBeNull();
	});
});

describe("getWebpayTransactionError / isWebpayChargeSuccess", () => {
	it("surfaces GraphQL errors first", () => {
		expect(getWebpayTransactionError({ errors: [{ message: "boom" }] })).toBe("boom");
	});

	it("surfaces a failed transaction event", () => {
		expect(
			getWebpayTransactionError({ transactionEvent: { type: "CHARGE_FAILURE", message: "rechazado" } }),
		).toBe("rechazado");
	});

	it("flags a missing transaction", () => {
		expect(getWebpayTransactionError({ transactionEvent: { type: "CHARGE_SUCCESS" } })).not.toBeNull();
	});

	it("passes a successful charge", () => {
		const payload = { transaction: { id: "t1" }, transactionEvent: { type: "CHARGE_SUCCESS" } };
		expect(getWebpayTransactionError(payload)).toBeNull();
		expect(isWebpayChargeSuccess(payload)).toBe(true);
	});

	it("does not treat action-required as success", () => {
		expect(isWebpayChargeSuccess({ transactionEvent: { type: "CHARGE_ACTION_REQUIRED" } })).toBe(false);
	});
});
