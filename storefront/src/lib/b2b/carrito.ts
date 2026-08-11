import "server-only";

import { getHeaderAuthState } from "@/lib/auth/get-header-user";
import { esCanalB2B } from "./canales";
import { b2bBaseUrl } from "./company";

/**
 * Aplica al carrito el precio por volumen que corresponde a cada cantidad.
 *
 * La ficha de producto publica «12 unidades, $9.130 c/u». Sin esto el carrito
 * cobra el precio de catálogo, y una tienda que muestra un precio y cobra otro
 * es peor que una que no muestra la tabla.
 *
 * Se llama después de cada cambio de líneas —agregar y cambiar cantidad—, porque
 * el precio depende de la cantidad y no hay forma de fijarlo antes de conocerla.
 *
 * Nunca lanza: si la App B2B no responde, el carrito conserva el precio de
 * catálogo. Más caro que el que corresponde, pero no es un cobro indebido, y
 * dejar el carrito inutilizable sí sería peor.
 */
export async function reprecificar(checkoutId: string, channel: string): Promise<void> {
	if (!esCanalB2B(channel)) return;

	const base = b2bBaseUrl();
	if (!base) return;

	const auth = await getHeaderAuthState();
	if (auth.status !== "authenticated") return;

	try {
		await fetch(`${base}/cart/reprecio`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			cache: "no-store",
			signal: AbortSignal.timeout(8000),
			body: JSON.stringify({ checkout_id: checkoutId, user_id: auth.user.id }),
		});
	} catch (error) {
		// Se registra y se sigue: el carrito ya tiene la línea, y el precio de
		// catálogo es un estado válido aunque no sea el deseado.
		console.error("No se pudo aplicar el precio por volumen:", error);
	}
}
