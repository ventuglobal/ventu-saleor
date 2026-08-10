import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { checkoutIdCookieName } from "@paper/session-bridge";
import { buildStorefrontPath } from "@/lib/storefront-path";

/**
 * `/c/{linkId}` — abre el carrito preparado en una conversación de WhatsApp.
 *
 * El enlace que recibe el cliente apunta a un identificador propio de Ventu, no
 * al del checkout de Saleor: un checkout no puede cambiar de canal ni sobrevive
 * indefinidamente, así que rehacerlo invalidaría el enlace que el cliente ya
 * tiene en su teléfono.
 *
 * Es un *route handler* y no una página porque su trabajo es fijar la cookie del
 * carrito y redirigir — y un componente de servidor no puede escribir cookies.
 */

/** Mismo alfabeto y largo que genera la App B2B (sin 0/O/1/l/I). */
const LINK_ID = /^[23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ]{22}$/;

type Resuelto = {
	checkout_id: string;
	canal: string | null;
};

export async function GET(_request: Request, { params }: { params: Promise<{ linkId: string }> }) {
	const { linkId } = await params;

	// Se valida la forma antes de consultar: una URL inventada no debe
	// convertirse en tráfico contra la App B2B.
	if (!LINK_ID.test(linkId)) {
		return NextResponse.redirect(new URL("/", process.env.NEXT_PUBLIC_STOREFRONT_URL ?? "http://localhost:3000"));
	}

	const base = process.env.B2B_APP_URL?.replace(/\/$/, "");
	const storefront = process.env.NEXT_PUBLIC_STOREFRONT_URL ?? "http://localhost:3000";
	if (!base) {
		return NextResponse.redirect(new URL("/", storefront));
	}

	let resuelto: Resuelto | null = null;
	try {
		const res = await fetch(`${base}/cart/${linkId}`, { cache: "no-store" });
		if (res.ok) {
			resuelto = (await res.json()) as Resuelto;
		}
	} catch {
		// La App B2B no respondió. Se trata igual que un enlace caducado: el
		// cliente llega a la tienda en vez de a una pantalla de error.
		resuelto = null;
	}

	if (!resuelto?.checkout_id) {
		// 410 en la App B2B significa "el enlace fue válido y ya no lo es".
		// Enviar al catálogo es preferible a un error: el cliente venía a comprar.
		return NextResponse.redirect(new URL("/products", storefront));
	}

	const canal = resuelto.canal ?? process.env.NEXT_PUBLIC_DEFAULT_CHANNEL ?? "";
	const destino = new URL(buildStorefrontPath(process.env.NEXT_PUBLIC_DEFAULT_LOCALE ?? "es", canal, "/cart"), storefront);
	const respuesta = NextResponse.redirect(destino);

	// Adoptar el carrito preparado por el ejecutivo: a partir de aquí el
	// storefront lo trata como el carrito del visitante.
	const store = await cookies();
	store.set(checkoutIdCookieName(canal), resuelto.checkout_id, {
		path: "/",
		httpOnly: false,
		sameSite: "lax",
		secure: storefront.startsWith("https://"),
		maxAge: 60 * 60 * 24 * 30,
	});

	return respuesta;
}
