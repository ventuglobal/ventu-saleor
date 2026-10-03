import { type PaymentGatewayLike } from "../types";

/**
 * Id de la Saleor App de pagos Ventu (Webpay/Transbank). Para una app de
 * Transactions, Saleor expone el gateway con el `id` del manifest. Ver
 * `apps/ventu-pagos` → `/manifest` (`id: "cl.ventu.pagos"`).
 */
export const WEBPAY_GATEWAY_ID = process.env.NEXT_PUBLIC_WEBPAY_GATEWAY_ID?.trim() || "cl.ventu.pagos";

/** Se muestra si Webpay llega al checkout pero está apagado en el storefront. */
export const WEBPAY_PAYMENT_NOT_ENABLED_MESSAGE =
	"Webpay no está habilitado en este ambiente. Revisa NEXT_PUBLIC_ENABLE_WEBPAY_PAYMENTS en el storefront.";

/** Se muestra si se intenta Webpay en un canal que no lo ofrece (p.ej. B2B). */
export const WEBPAY_CHANNEL_NOT_ALLOWED_MESSAGE = "Webpay no está disponible en este canal.";

export function isWebpayGateway(gatewayId: string): boolean {
	return gatewayId === WEBPAY_GATEWAY_ID;
}

export function findWebpayGateway(
	gateways: ReadonlyArray<PaymentGatewayLike> | null | undefined,
): PaymentGatewayLike | undefined {
	return gateways?.find((gateway) => isWebpayGateway(gateway.id));
}

/**
 * Webpay es el medio de pago de retail: encendido por defecto. Se puede apagar
 * con `NEXT_PUBLIC_ENABLE_WEBPAY_PAYMENTS=false` (o `ENABLE_WEBPAY_PAYMENTS=false`
 * server-side). El aislamiento por canal lo hace `esCanalWebpay`, no este flag.
 */
export function isWebpayPaymentEnabled(): boolean {
	if (process.env.ENABLE_WEBPAY_PAYMENTS === "false") {
		return false;
	}
	if (process.env.NEXT_PUBLIC_ENABLE_WEBPAY_PAYMENTS === "false") {
		return false;
	}
	return true;
}

/** Canales habilitados server-side (borde de seguridad). */
function webpayServerChannels(): string[] {
	const raw = process.env.WEBPAY_CHANNELS ?? process.env.NEXT_PUBLIC_WEBPAY_CHANNELS ?? "retail-cl";
	return raw
		.split(",")
		.map((c) => c.trim())
		.filter(Boolean);
}

/**
 * Guard server-side para `transactionInitialize`: bloquea Webpay cuando el flag
 * está apagado. Espeja `getStripePaymentGuardError`.
 */
export function getWebpayPaymentGuardError(gatewayId: string | null | undefined): string | null {
	if (!gatewayId || !isWebpayGateway(gatewayId)) {
		return null;
	}
	if (isWebpayPaymentEnabled()) {
		return null;
	}
	return WEBPAY_PAYMENT_NOT_ENABLED_MESSAGE;
}

/**
 * Guard server-side de canal: Webpay solo corre en `WEBPAY_CHANNELS`. Es el borde
 * de seguridad; el filtro de UI (`esCanalWebpay`) es defensa en profundidad, no la
 * única barrera (la resolución de providers es channel-blind).
 */
export function getWebpayChannelGuardError(
	gatewayId: string | null | undefined,
	channelSlug: string | null | undefined,
): string | null {
	if (!gatewayId || !isWebpayGateway(gatewayId)) {
		return null;
	}
	if (channelSlug && webpayServerChannels().includes(channelSlug)) {
		return null;
	}
	return WEBPAY_CHANNEL_NOT_ALLOWED_MESSAGE;
}

/**
 * Datos de redirección que devuelve ventu-pagos en `transactionInitialize.data`
 * (ver `handlers.action_required_response`): `{ webpayUrl, token }`.
 */
export type WebpayRedirect = {
	webpayUrl: string;
	token: string;
};

export function parseWebpayRedirect(data: unknown): WebpayRedirect | null {
	if (!data || typeof data !== "object") {
		return null;
	}
	const record = data as Record<string, unknown>;
	const webpayUrl = record.webpayUrl;
	const token = record.token;
	if (typeof webpayUrl !== "string" || !webpayUrl.trim()) {
		return null;
	}
	if (typeof token !== "string" || !token.trim()) {
		return null;
	}
	return { webpayUrl, token };
}

const FAILED_TRANSACTION_EVENT_TYPES = new Set([
	"AUTHORIZATION_FAILURE",
	"CHARGE_FAILURE",
	"REFUND_FAILURE",
	"CANCEL_FAILURE",
]);

type TransactionPayload = {
	errors?: ReadonlyArray<{ message?: string | null }> | null;
	transactionEvent?: { type?: string | null; message?: string | null } | null;
	transaction?: { id?: string | null } | null;
	data?: unknown;
};

/** Error legible cuando initialize/process de Webpay no salió bien. */
export function getWebpayTransactionError(payload: TransactionPayload | null | undefined): string | null {
	const errors = payload?.errors;
	if (errors?.length) {
		return errors[0]?.message || "No se pudo iniciar el pago con Webpay.";
	}

	const eventType = payload?.transactionEvent?.type;
	const eventMessage = payload?.transactionEvent?.message;
	if (eventType && FAILED_TRANSACTION_EVENT_TYPES.has(eventType)) {
		return eventMessage || "El pago con Webpay fue rechazado.";
	}

	if (!payload?.transaction?.id) {
		return "No se pudo procesar el pago. Revisa que la app de pagos esté activa en Saleor.";
	}

	return null;
}

/** ¿El evento de la transacción indica un cobro exitoso? (regla de oro server-side). */
export function isWebpayChargeSuccess(payload: TransactionPayload | null | undefined): boolean {
	return payload?.transactionEvent?.type === "CHARGE_SUCCESS";
}
