"use server";

import { writeWebpayContextCookie, type WebpayContext } from "./checkout/webpay/webpay-context";

/**
 * Server action que el componente de Webpay llama justo antes de redirigir a
 * Transbank: persiste `{checkoutId, transactionId, channel, browseLocale}` en una
 * cookie httpOnly para poder cerrar la orden cuando Transbank devuelva al
 * `return_url` (ver `webpay-context.ts` por qué no basta el querystring).
 */
export async function storeWebpayContext(ctx: WebpayContext): Promise<void> {
	await writeWebpayContextCookie(ctx);
}
