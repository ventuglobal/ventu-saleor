import { type NextRequest, NextResponse } from "next/server";
import { processCheckoutTransaction, runCheckoutComplete } from "@/app/(checkout)/actions";
import { isWebpayChargeSuccess } from "@/checkout/lib/payment/providers/webpay";
import { buildCheckoutPath, buildOrderConfirmationPath } from "@/session-bridge/checkout-url";
import {
	clearWebpayContextCookie,
	clearWebpayTokenCookie,
	readWebpayContextCookie,
	readWebpayTokenCookie,
	writeWebpayTokenCookie,
	type WebpayContext,
} from "../webpay-context";

/**
 * `return_url` fijo de Webpay. Transbank hace un POST cross-site aquí; ese POST no
 * trae cookies `SameSite=Lax`, así que el POST solo guarda el `token_ws` en una
 * cookie efímera y hace 303 al mismo path por GET (same-site), donde ya llegan la
 * sesión de Saleor y el contexto para cerrar la orden. Ver `webpay-context.ts`.
 *
 * El handler lee `request.formData()` y cookies, así que ya es dinámico por
 * naturaleza; no se declara `dynamic = "force-dynamic"` porque es incompatible
 * con Cache Components (Next 16).
 */

function sameOrigin(request: NextRequest, path: string): URL {
	return new URL(path, request.nextUrl.origin);
}

function backToPayment(
	request: NextRequest,
	ctx: WebpayContext | null,
	outcome: "failed" | "aborted" | "timeout" | "error",
): URL {
	if (!ctx) {
		// Sin contexto no podemos reconstruir el checkout: el shell recupera el
		// checkout guardado en cookie.
		return sameOrigin(request, "/checkout");
	}
	if (ctx.kind === "order") {
		// B2B orden-primero: la orden ya existe por pagar. Se vuelve a su
		// confirmación con el aviso, donde se ofrece reintentar el pago.
		const url = sameOrigin(request, buildOrderConfirmationPath({ orderId: ctx.orderId }));
		url.searchParams.set("webpay", outcome);
		return url;
	}
	const path = buildCheckoutPath({
		checkoutId: ctx.checkoutId,
		step: "payment",
		browseLocale: ctx.browseLocale,
	});
	const url = sameOrigin(request, path);
	url.searchParams.set("webpay", outcome);
	return url;
}

/** Transbank POSTea el resultado; solo trasladamos el token al GET same-site. */
export async function POST(request: NextRequest): Promise<NextResponse> {
	const form = await request.formData();
	const tokenWs = form.get("token_ws");
	const tbkToken = form.get("TBK_TOKEN");

	const redirectTo = sameOrigin(request, "/checkout/webpay/retorno");

	if (typeof tokenWs === "string" && tokenWs) {
		// Flujo normal: el cliente completó el formulario de Webpay.
		await writeWebpayTokenCookie(tokenWs);
	} else if (typeof tbkToken === "string" && tbkToken) {
		// El cliente anuló el pago en el formulario de Webpay.
		redirectTo.searchParams.set("webpay", "aborted");
	} else {
		// Solo TBK_ORDEN_COMPRA (o nada): el formulario expiró / timeout.
		redirectTo.searchParams.set("webpay", "timeout");
	}

	// 303: fuerza GET same-site, recuperando las cookies Lax.
	return NextResponse.redirect(redirectTo, { status: 303 });
}

export async function GET(request: NextRequest): Promise<NextResponse> {
	const ctx = await readWebpayContextCookie();
	const abortedParam = request.nextUrl.searchParams.get("webpay");

	// El POST ya clasificó anulación/timeout: no hay commit que hacer.
	if (abortedParam === "aborted" || abortedParam === "timeout") {
		await clearWebpayTokenCookie();
		await clearWebpayContextCookie();
		return NextResponse.redirect(
			backToPayment(request, ctx, abortedParam === "aborted" ? "aborted" : "timeout"),
		);
	}

	const token = await readWebpayTokenCookie();

	// Sin token o sin contexto no podemos confirmar (regla de oro: nada se da por
	// bueno sin el commit de nuestro servidor).
	if (!token || !ctx) {
		await clearWebpayTokenCookie();
		await clearWebpayContextCookie();
		return NextResponse.redirect(backToPayment(request, ctx, "error"));
	}

	// Dispara TRANSACTION_PROCESS_SESSION → ventu-pagos hace el commit en Transbank
	// y responde el resultado sincrónicamente (la aprobación la decide el servidor).
	const processResult = await processCheckoutTransaction({
		id: ctx.transactionId,
		data: { token_ws: token },
	});

	await clearWebpayTokenCookie();

	if (!processResult.ok || !isWebpayChargeSuccess(processResult.data)) {
		await clearWebpayContextCookie();
		return NextResponse.redirect(backToPayment(request, ctx, "failed"));
	}

	// Cobro confirmado por nuestro servidor (regla de oro).
	await clearWebpayContextCookie();

	if (ctx.kind === "order") {
		// B2B orden-primero: la orden ya existe; el cobro solo la marca pagada
		// (`ORDER_FULLY_PAID`). No hay `checkoutComplete` que llamar.
		return NextResponse.redirect(
			sameOrigin(request, buildOrderConfirmationPath({ orderId: ctx.orderId })),
		);
	}

	// Retail: convertir el checkout en orden.
	const completeResult = await runCheckoutComplete(ctx.checkoutId);

	if (!completeResult.ok || !completeResult.orderId) {
		// El pago quedó cobrado pero la orden no cerró: el reconciliador/soporte lo
		// resuelve; devolvemos al checkout con aviso en vez de a confirmación.
		return NextResponse.redirect(backToPayment(request, ctx, "failed"));
	}

	return NextResponse.redirect(
		sameOrigin(request, buildOrderConfirmationPath({ orderId: completeResult.orderId })),
	);
}
