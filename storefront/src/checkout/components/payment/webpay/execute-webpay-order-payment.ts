import { initializeOrderTransaction } from "@/app/(checkout)/actions";
import { storeWebpayContext } from "@/app/(checkout)/webpay-actions";
import {
	getWebpayTransactionError,
	parseWebpayRedirect,
	WEBPAY_GATEWAY_ID,
} from "@/checkout/lib/payment/providers/webpay";
import { rethrowNextInternalError } from "@/checkout/lib/rethrow-next-internal-error";

/**
 * Pago con Webpay **sobre una orden ya creada** (B2B orden-primero).
 *
 * A diferencia del camino retail (`execute-webpay-checkout-payment`), aquí la orden
 * ya existe por pagar: no hay checkout que refrescar ni `checkoutComplete` que
 * llamar. El monto y el canal los decide el servidor desde la orden
 * (`initializeOrderTransaction`), no el cliente. Solo queda inicializar la
 * transacción y hacer el auto-POST a Transbank.
 */

export const WEBPAY_ORDER_MESSAGES = {
	initFailed: "No pudimos iniciar el pago con Webpay. Inténtalo nuevamente.",
	redirectUnavailable: "Webpay no devolvió los datos de redirección. Inténtalo nuevamente.",
	unexpectedError: "Ocurrió un error inesperado al iniciar el pago. Inténtalo nuevamente.",
} as const;

export type WebpayOrderPayResult = { ok: true } | { ok: false; message: string };

type ExecuteWebpayOrderPaymentParams = {
	orderId: string;
	channel: string;
	/** Locale de navegación para reconstruir la URL de vuelta tras Transbank. */
	browseLocale?: string;
};

let payInFlight: Promise<WebpayOrderPayResult> | null = null;

/**
 * Single-flight: un doble clic no debe crear dos transacciones de Saleor ni dos
 * formularios de Transbank para la misma orden.
 */
export async function executeWebpayOrderPayment(
	params: ExecuteWebpayOrderPaymentParams,
): Promise<WebpayOrderPayResult> {
	if (payInFlight) {
		return payInFlight;
	}

	const run = runWebpayOrderPayment(params);
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

async function runWebpayOrderPayment({
	orderId,
	channel,
	browseLocale,
}: ExecuteWebpayOrderPaymentParams): Promise<WebpayOrderPayResult> {
	try {
		const initResult = await initializeOrderTransaction(orderId, {
			id: WEBPAY_GATEWAY_ID,
			data: {},
		});

		if (!initResult.ok) {
			return { ok: false, message: initResult.error };
		}

		const transactionError = getWebpayTransactionError(initResult.data);
		if (transactionError) {
			return { ok: false, message: transactionError };
		}

		const redirect = parseWebpayRedirect(initResult.data.data);
		const transactionId = initResult.data.transaction?.id;

		if (!redirect || !transactionId) {
			return { ok: false, message: WEBPAY_ORDER_MESSAGES.redirectUnavailable };
		}

		// Puente de estado ANTES de salir: el retorno cross-site de Transbank no trae
		// cookies, lo recuperamos del contexto httpOnly. `kind: "order"` hace que el
		// retorno NO llame `checkoutComplete` (la orden ya existe).
		await storeWebpayContext({
			kind: "order",
			orderId,
			transactionId,
			channel,
			browseLocale,
		});

		submitWebpayRedirect(redirect.webpayUrl, redirect.token);

		// La pestaña navega al formulario de Webpay; el llamador mantiene "pagando".
		return { ok: true };
	} catch (error) {
		rethrowNextInternalError(error);
		console.error("Webpay order payment failed:", error);
		return { ok: false, message: WEBPAY_ORDER_MESSAGES.unexpectedError };
	}
}
