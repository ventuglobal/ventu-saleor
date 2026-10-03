import { cookies } from "next/headers";

/**
 * Puente de estado para el retorno de Webpay.
 *
 * Transbank vuelve con un POST cross-site a un `return_url` FIJO; en ese POST el
 * navegador NO manda cookies `SameSite=Lax` (ni la sesión de Saleor ni este
 * contexto). Por eso el handler de retorno hace POST→GET (303) al mismo origen:
 * recién en el GET same-site llegan las cookies Lax. Guardamos aquí lo mínimo
 * para, de vuelta, mapear `token_ws` → transacción de Saleor y cerrar la orden.
 *
 * El `token_ws` (que sí llega en el body del POST) se traspasa al GET con una
 * cookie efímera aparte (`WEBPAY_TOKEN_COOKIE`), no por querystring (evita dejar
 * el token en logs/historial).
 */
export const WEBPAY_CTX_COOKIE = "webpay_ctx";
export const WEBPAY_TOKEN_COOKIE = "webpay_token";

/** Vive solo entre el inicio del pago y el retorno (~30 min cubre el formulario Webpay). */
const WEBPAY_CTX_MAX_AGE_SECONDS = 60 * 30;
/** El token solo cruza el salto POST→GET: segundos. */
const WEBPAY_TOKEN_MAX_AGE_SECONDS = 60 * 2;

export type WebpayContext = {
	checkoutId: string;
	transactionId: string;
	channel: string;
	/** Locale de navegación para reconstruir la URL del checkout al volver. */
	browseLocale?: string;
};

function isSecureCookie(): boolean {
	return process.env.NODE_ENV === "production";
}

export async function writeWebpayContextCookie(ctx: WebpayContext): Promise<void> {
	const cookieStore = await cookies();
	cookieStore.set(WEBPAY_CTX_COOKIE, JSON.stringify(ctx), {
		httpOnly: true,
		sameSite: "lax",
		secure: isSecureCookie(),
		path: "/",
		maxAge: WEBPAY_CTX_MAX_AGE_SECONDS,
	});
}

export async function readWebpayContextCookie(): Promise<WebpayContext | null> {
	const cookieStore = await cookies();
	const raw = cookieStore.get(WEBPAY_CTX_COOKIE)?.value;
	if (!raw) {
		return null;
	}
	try {
		const parsed = JSON.parse(raw) as Partial<WebpayContext>;
		if (
			typeof parsed.checkoutId === "string" &&
			typeof parsed.transactionId === "string" &&
			typeof parsed.channel === "string"
		) {
			return {
				checkoutId: parsed.checkoutId,
				transactionId: parsed.transactionId,
				channel: parsed.channel,
				browseLocale: typeof parsed.browseLocale === "string" ? parsed.browseLocale : undefined,
			};
		}
	} catch {
		// cookie corrupta o manipulada → se trata como ausente
	}
	return null;
}

export async function clearWebpayContextCookie(): Promise<void> {
	const cookieStore = await cookies();
	cookieStore.delete(WEBPAY_CTX_COOKIE);
}

/** Guarda el `token_ws` para el salto POST→GET del mismo origen. */
export async function writeWebpayTokenCookie(token: string): Promise<void> {
	const cookieStore = await cookies();
	cookieStore.set(WEBPAY_TOKEN_COOKIE, token, {
		httpOnly: true,
		sameSite: "lax",
		secure: isSecureCookie(),
		path: "/",
		maxAge: WEBPAY_TOKEN_MAX_AGE_SECONDS,
	});
}

export async function readWebpayTokenCookie(): Promise<string | null> {
	const cookieStore = await cookies();
	return cookieStore.get(WEBPAY_TOKEN_COOKIE)?.value ?? null;
}

export async function clearWebpayTokenCookie(): Promise<void> {
	const cookieStore = await cookies();
	cookieStore.delete(WEBPAY_TOKEN_COOKIE);
}
