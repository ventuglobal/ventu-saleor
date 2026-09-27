import "server-only";

import { getHeaderAuthState } from "@/lib/auth/get-header-user";
import { esCanalB2B } from "./canales";
import { avisarSiRechazaToken, b2bBaseUrl, b2bHeaders } from "./company";

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
 * `canalDelCheckout` es el canal que Saleor devolvió para ese carrito en la
 * misma mutación de líneas, nunca el que manda el navegador: la acción de
 * servidor se puede invocar con cualquier argumento, y un carrito retail
 * presentado como `b2b-cl` terminaría con precios por volumen cobrados por la
 * pasarela retail. Sin canal conocido no se reprecifica.
 *
 * Nunca lanza: si la App B2B no responde, el carrito conserva el precio de
 * catálogo. Más caro que el que corresponde, pero no es un cobro indebido, y
 * dejar el carrito inutilizable sí sería peor.
 */
export async function reprecificar(
	checkoutId: string,
	canalDelCheckout: string | null | undefined,
): Promise<void> {
	if (!canalDelCheckout || !esCanalB2B(canalDelCheckout)) return;

	const base = b2bBaseUrl();
	if (!base) return;

	const auth = await getHeaderAuthState();
	if (auth.status !== "authenticated") return;

	try {
		const res = await fetch(`${base}/cart/reprecio`, {
			method: "POST",
			headers: b2bHeaders({ "Content-Type": "application/json" }),
			cache: "no-store",
			signal: AbortSignal.timeout(8000),
			body: JSON.stringify({ checkout_id: checkoutId, user_id: auth.user.id }),
		});
		avisarSiRechazaToken(res, "/cart/reprecio");
		if (!res.ok) {
			// Mismo criterio que un fallo de red: el carrito queda a precio de
			// catálogo. Se registra el motivo porque, sin esto, un rechazo de la
			// App B2B pasaría inadvertido hasta que alguien note el precio.
			const cuerpo = (await res.json().catch(() => null)) as { detail?: unknown } | null;
			console.error(`La App B2B no aplicó el precio por volumen (${res.status}):`, cuerpo?.detail ?? "");
		}
	} catch (error) {
		// Se registra y se sigue: el carrito ya tiene la línea, y el precio de
		// catálogo es un estado válido aunque no sea el deseado.
		console.error("No se pudo aplicar el precio por volumen:", error);
	}
}
