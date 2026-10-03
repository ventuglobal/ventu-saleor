import { storeWebpayContext } from "@/app/(checkout)/webpay-actions";
import { type CheckoutFragment } from "@/checkout/graphql";
import { getCheckoutTransport } from "@/checkout/lib/checkout-transport";
import {
	buildCheckoutPriceChangeNotice,
	getCheckoutPayAmount,
	getCheckoutPayCurrency,
	hasMaterialCheckoutTotalChange,
	type CheckoutPriceChangeNotice,
} from "@/checkout/lib/payment/checkout-pay-amount";
import {
	getWebpayTransactionError,
	parseWebpayRedirect,
	WEBPAY_GATEWAY_ID,
} from "@/checkout/lib/payment/providers/webpay";
import { updateCheckoutBilling } from "@/checkout/lib/payment/update-billing";
import { rethrowNextInternalError } from "@/checkout/lib/rethrow-next-internal-error";
import { type WebpayBillingContext } from "./webpay-billing-context";

/** Copys en español: Webpay es solo del canal retail chileno (ver plan Fase 3). */
export const WEBPAY_MESSAGES = {
	totalsRefreshFailed: "No pudimos verificar el total del pedido. Inténtalo nuevamente.",
	totalUnavailable: "El total del pedido no está disponible. Actualiza la página e inténtalo de nuevo.",
	currencyUnavailable: "La moneda del pedido no está disponible. Actualiza la página e inténtalo de nuevo.",
	channelUnavailable: "No pudimos determinar el canal del pedido. Actualiza la página e inténtalo de nuevo.",
	initFailed: "No pudimos iniciar el pago con Webpay. Inténtalo nuevamente.",
	redirectUnavailable: "Webpay no devolvió los datos de redirección. Inténtalo nuevamente.",
	unexpectedError: "Ocurrió un error inesperado al iniciar el pago. Inténtalo nuevamente.",
} as const;

export type WebpayCheckoutPayResult =
	| { ok: true }
	| { ok: false; kind: "error"; message: string }
	| { ok: false; kind: "billing"; errors: Record<string, string>; focusField?: string }
	| { ok: false; kind: "price_change"; notice: CheckoutPriceChangeNotice };

type ExecuteWebpayCheckoutPaymentParams = {
	checkout: CheckoutFragment;
	billing: WebpayBillingContext;
	refreshCheckout: (options?: { updateState?: boolean }) => Promise<CheckoutFragment | null>;
	/** Locale de navegación para reconstruir la URL del checkout al volver de Transbank. */
	browseLocale?: string;
};

let payInFlight: Promise<WebpayCheckoutPayResult> | null = null;

/**
 * Single-flight: un doble clic no debe crear dos transacciones de Saleor ni dos
 * `webpay.create()` (y por tanto dos formularios de Transbank).
 */
export async function executeWebpayCheckoutPayment(
	params: ExecuteWebpayCheckoutPaymentParams,
): Promise<WebpayCheckoutPayResult> {
	if (payInFlight) {
		return payInFlight;
	}

	const run = runWebpayCheckoutPayment(params);
	payInFlight = run;

	try {
		return await run;
	} finally {
		if (payInFlight === run) {
			payInFlight = null;
		}
	}
}

/**
 * Auto-POST al portal de Transbank: construye un form `token_ws` → `webpayUrl` y lo
 * envía, llevándose la pestaña actual al formulario de pago de Webpay.
 */
function submitWebpayRedirect(webpayUrl: string, token: string): void {
	const form = document.createElement("form");
	form.method = "POST";
	form.action = webpayUrl;
	form.style.display = "none";

	const input = document.createElement("input");
	input.type = "hidden";
	input.name = "token_ws";
	input.value = token;
	form.appendChild(input);

	document.body.appendChild(form);
	form.submit();
}

async function runWebpayCheckoutPayment({
	checkout,
	billing,
	refreshCheckout,
	browseLocale,
}: ExecuteWebpayCheckoutPaymentParams): Promise<WebpayCheckoutPayResult> {
	try {
		const billingResult = await updateCheckoutBilling({
			checkoutId: checkout.id,
			sameAsBilling: billing.sameAsBilling,
			hasShippingAddress: billing.hasShippingAddress,
			billingData: billing.billingData,
			shippingAddress: billing.shippingAddress,
			userAddresses: billing.userAddresses,
			authenticated: billing.authenticated,
		});

		if (!billingResult.ok) {
			return {
				ok: false,
				kind: "billing",
				errors: billingResult.errors,
				focusField: billingResult.focusField,
			};
		}

		const liveCheckout = await refreshCheckout({ updateState: false });
		if (!liveCheckout) {
			return { ok: false, kind: "error", message: WEBPAY_MESSAGES.totalsRefreshFailed };
		}

		const displayedAmount = getCheckoutPayAmount(checkout);
		const payAmount = getCheckoutPayAmount(liveCheckout);
		if (payAmount === null) {
			return { ok: false, kind: "error", message: WEBPAY_MESSAGES.totalUnavailable };
		}

		const currency = getCheckoutPayCurrency(liveCheckout);
		if (!currency) {
			return { ok: false, kind: "error", message: WEBPAY_MESSAGES.currencyUnavailable };
		}

		const channelSlug = liveCheckout.channel?.slug;
		if (!channelSlug) {
			return { ok: false, kind: "error", message: WEBPAY_MESSAGES.channelUnavailable };
		}

		if (displayedAmount !== null && hasMaterialCheckoutTotalChange(displayedAmount, payAmount)) {
			return {
				ok: false,
				kind: "price_change",
				notice: buildCheckoutPriceChangeNotice(displayedAmount, payAmount, currency),
			};
		}

		const initResult = await getCheckoutTransport().initializeTransaction({
			checkoutId: liveCheckout.id,
			amount: payAmount,
			paymentGateway: {
				id: WEBPAY_GATEWAY_ID,
				data: {},
			},
		});

		if (!initResult.ok) {
			return { ok: false, kind: "error", message: initResult.error };
		}

		const transactionError = getWebpayTransactionError(initResult.data);
		if (transactionError) {
			return { ok: false, kind: "error", message: transactionError };
		}

		const redirect = parseWebpayRedirect(initResult.data.data);
		const transactionId = initResult.data.transaction?.id;

		if (!redirect || !transactionId) {
			return { ok: false, kind: "error", message: WEBPAY_MESSAGES.redirectUnavailable };
		}

		// Persistimos el puente de estado ANTES de salir: el retorno cross-site de
		// Transbank no trae cookies, lo recuperamos del contexto httpOnly.
		await storeWebpayContext({
			checkoutId: liveCheckout.id,
			transactionId,
			channel: channelSlug,
			browseLocale,
		});

		submitWebpayRedirect(redirect.webpayUrl, redirect.token);

		// La pestaña navega al formulario de Webpay; mantenemos el estado "pagando".
		return { ok: true };
	} catch (error) {
		rethrowNextInternalError(error);
		console.error("Webpay payment failed:", error);
		return { ok: false, kind: "error", message: WEBPAY_MESSAGES.unexpectedError };
	}
}
