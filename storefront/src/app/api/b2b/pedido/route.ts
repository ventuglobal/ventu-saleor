import { NextResponse, type NextRequest } from "next/server";

import { getHeaderAuthState } from "@/lib/auth/get-header-user";
import { b2bBaseUrl } from "@/lib/b2b/company";
import * as Checkout from "@/lib/checkout";

/**
 * Cierra el carrito B2B como pedido.
 *
 * No pasa por `checkoutComplete`: esa mutación exige que el total esté cubierto,
 * que es la regla correcta para una venta al consumidor y la equivocada para una
 * venta a 30 días. La App B2B usa `orderCreateFromCheckout`, y el pedido nace
 * **por pagar**.
 *
 * El id del checkout se toma de la cookie del canal, no del cuerpo: así nadie
 * puede cerrar el carrito de otra persona enviando su id.
 */

type PedidoRequest = {
	canal?: string;
	metodoPago?: string;
};

export async function POST(request: NextRequest) {
	const base = b2bBaseUrl();
	if (!base) {
		return NextResponse.json({ mensaje: "El pedido B2B no está configurado." }, { status: 503 });
	}

	const auth = await getHeaderAuthState();
	if (auth.status !== "authenticated") {
		return NextResponse.json({ mensaje: "Inicia sesión para comprar." }, { status: 401 });
	}

	let cuerpo: PedidoRequest;
	try {
		cuerpo = (await request.json()) as PedidoRequest;
	} catch {
		return NextResponse.json({ mensaje: "Solicitud inválida." }, { status: 400 });
	}

	const canal = cuerpo.canal?.trim();
	const metodoPago = cuerpo.metodoPago?.trim();
	if (!canal || !metodoPago) {
		return NextResponse.json({ mensaje: "Falta el canal o el medio de pago." }, { status: 400 });
	}

	const checkoutId = await Checkout.getIdFromCookies(canal);
	if (!checkoutId) {
		return NextResponse.json({ mensaje: "No hay un carrito abierto." }, { status: 409 });
	}

	try {
		const res = await fetch(`${base}/pedido`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			cache: "no-store",
			signal: AbortSignal.timeout(20_000),
			body: JSON.stringify({
				checkout_id: checkoutId,
				user_id: auth.user.id,
				metodo_pago: metodoPago,
			}),
		});

		const dato = (await res.json().catch(() => null)) as Record<string, unknown> | null;

		if (!res.ok) {
			// La App B2B explica por qué —medio sin crédito aprobado, stock
			// insuficiente— y ese texto le sirve al cliente para decidir qué hacer.
			const mensaje = typeof dato?.detail === "string" ? dato.detail : "No se pudo crear el pedido.";
			return NextResponse.json({ mensaje }, { status: res.status });
		}

		// El carrito ya no existe en Saleor (`removeCheckout`), así que la cookie
		// que lo apunta tampoco debe sobrevivir: si no, la tienda mostraría un
		// carrito fantasma.
		await Checkout.clearCheckoutCookie(canal);

		return NextResponse.json(dato ?? {});
	} catch {
		return NextResponse.json({ mensaje: "El servicio de pedidos no respondió." }, { status: 503 });
	}
}
