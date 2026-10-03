/**
 * Marca de sesión para reintentar el pago con tarjeta de una orden B2B.
 *
 * Cuando el pago con Webpay de una orden recién creada falla o se anula, la orden
 * queda por pagar y el cliente vuelve a su confirmación. Allí se ofrece
 * «reintentar pago», pero **solo en la misma sesión del navegador** que creó la
 * orden: la recuperación desde cualquier sesión (vista de orden) es Fase 2b.
 *
 * `sessionStorage` acota el alcance a esta pestaña/sesión y sobrevive al viaje a
 * Transbank y de vuelta. Toda lectura/escritura va en try/catch: en modo privado
 * o con el storage bloqueado simplemente no se ofrece el reintento (nunca rompe).
 */
const KEY = "webpay.order.pending";

export function markWebpayOrderPending(orderId: string): void {
	try {
		window.sessionStorage.setItem(KEY, orderId);
	} catch {
		// storage no disponible → sin reintento en sesión, no es un error fatal.
	}
}

export function isWebpayOrderPendingInSession(orderId: string): boolean {
	try {
		return window.sessionStorage.getItem(KEY) === orderId;
	} catch {
		return false;
	}
}

export function clearWebpayOrderPending(orderId: string): void {
	try {
		if (window.sessionStorage.getItem(KEY) === orderId) {
			window.sessionStorage.removeItem(KEY);
		}
	} catch {
		// nada que limpiar si el storage no está disponible.
	}
}
