import { NextResponse, type NextRequest } from "next/server";

import { getHeaderAuthState } from "@/lib/auth/get-header-user";
import { esCanalB2B } from "@/lib/b2b/canales";
import { avisarSiRechazaToken, b2bBaseUrl, b2bHeaders } from "@/lib/b2b/company";
import { errorDePedido } from "@/lib/b2b/errores";
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

/**
 * Presupuesto de espera. Crear la orden en Saleor y reservar stock puede tardar
 * varios segundos; cortar antes arriesga que el pedido se cree igual y el
 * comprador, sin confirmación, lo repita.
 */
const TIMEOUT_MS = 30_000;

/**
 * Las instrucciones de pago (datos de la transferencia, por ejemplo) se
 * muestran como texto al comprador. Solo se acepta un texto no vacío: cualquier
 * otra cosa se normaliza a `null` para que la confirmación use su mensaje de
 * siempre en vez de pintar un objeto ajeno.
 */
function instruccionesDePago(valor: unknown): string | null {
	return typeof valor === "string" && valor.trim() ? valor : null;
}

function esTimeout(error: unknown): boolean {
	return error instanceof DOMException && (error.name === "TimeoutError" || error.name === "AbortError");
}

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

	// El pedido por pagar es exclusivo de los canales de empresa. En un canal
	// retail el carrito se paga con la pasarela; dejar pasar este atajo ahí
	// permitiría llevarse mercadería a precio de consumidor sin pagarla.
	if (!esCanalB2B(canal)) {
		return NextResponse.json({ mensaje: "Este canal no admite pedidos de empresa." }, { status: 403 });
	}

	const checkoutId = await Checkout.getIdFromCookies(canal);
	if (!checkoutId) {
		return NextResponse.json({ mensaje: "No hay un carrito abierto." }, { status: 409 });
	}

	try {
		const res = await fetch(`${base}/pedido`, {
			method: "POST",
			headers: b2bHeaders({ "Content-Type": "application/json" }),
			cache: "no-store",
			signal: AbortSignal.timeout(TIMEOUT_MS),
			body: JSON.stringify({
				checkout_id: checkoutId,
				user_id: auth.user.id,
				metodo_pago: metodoPago,
			}),
		});

		const dato = (await res.json().catch(() => null)) as Record<string, unknown> | null;

		avisarSiRechazaToken(res, "/pedido");
		if (res.status === 401) {
			// Token mal configurado: es nuestro, no del comprador. Un «no
			// autorizado» lo haría dudar de su cuenta.
			return NextResponse.json({ mensaje: "El servicio de pedidos no está disponible." }, { status: 503 });
		}

		if (!res.ok) {
			// La App B2B explica por qué —empresa en revisión (403), medio sin
			// crédito (409), carrito inválido (422), Saleor caído (502/504)—, pero
			// con textos y códigos pensados para el log. Al navegador va solo el
			// mensaje traducido y un código estable; el cuerpo crudo queda aquí.
			console.warn(`(b2b) La App B2B rechazó el pedido (${res.status}):`, JSON.stringify(dato));
			const { mensaje, code } = errorDePedido(res.status, dato);
			return NextResponse.json({ mensaje, ...(code ? { code } : {}) }, { status: res.status });
		}

		// El carrito ya no existe en Saleor (`removeCheckout`), así que la cookie
		// que lo apunta tampoco debe sobrevivir: si no, la tienda mostraría un
		// carrito fantasma.
		await Checkout.clearCheckoutCookie(canal);

		return NextResponse.json({ ...dato, instrucciones_pago: instruccionesDePago(dato?.instrucciones_pago) });
	} catch (error) {
		if (esTimeout(error)) {
			// Sin respuesta no sabemos si el pedido se creó. Pedir que revise sus
			// pedidos antes de reintentar evita duplicarlo.
			return NextResponse.json(
				{
					mensaje:
						"El pedido está tardando más de lo normal. Revisa «Mis pedidos» antes de volver a intentarlo.",
				},
				{ status: 504 },
			);
		}
		console.error("(b2b) No se pudo llamar a /pedido:", error instanceof Error ? error.name : error);
		return NextResponse.json({ mensaje: "El servicio de pedidos no respondió." }, { status: 503 });
	}
}
