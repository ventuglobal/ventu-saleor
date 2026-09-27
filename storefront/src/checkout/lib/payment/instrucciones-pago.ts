/**
 * Instrucciones de pago de un pedido de empresa, desde la respuesta de
 * `/api/b2b/pedido` hasta la página de confirmación.
 *
 * La confirmación se abre con `window.location.replace`, así que el estado de
 * React no llega a ella, y la App B2B entrega las instrucciones solo al crear el
 * pedido: no hay dónde volver a pedirlas. `sessionStorage` sobrevive a esa
 * navegación, también a recargar la confirmación, y muere con la pestaña, que
 * es lo que dura su utilidad. La clave lleva el id del pedido para que un
 * segundo pedido en la misma pestaña no muestre los datos del primero.
 *
 * Toda lectura y escritura va en try/catch: el almacenamiento puede no existir
 * (navegación privada, cuota llena, cookies bloqueadas) y eso no debe romper la
 * compra. Quien guarda recibe `false` y muestra las instrucciones en el acto.
 */

const PREFIJO = "ventu:instrucciones-pago:";

export function guardarInstruccionesPago(orderId: string, instrucciones: string): boolean {
	try {
		globalThis.sessionStorage.setItem(PREFIJO + orderId, instrucciones);
		return true;
	} catch {
		return false;
	}
}

export function leerInstruccionesPago(orderId: string): string | null {
	try {
		const valor = globalThis.sessionStorage.getItem(PREFIJO + orderId);
		return valor?.trim() ? valor : null;
	} catch {
		return null;
	}
}
