"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

import { Button } from "@/ui/components/ui/button";
import { executeWebpayOrderPayment } from "@/checkout/components/payment/webpay/execute-webpay-order-payment";
import {
	clearWebpayOrderPending,
	isWebpayOrderPendingInSession,
} from "@/checkout/lib/payment/webpay-order-retry";

/** `sessionStorage` no avisa cambios en la misma pestaña; basta leerlo al montar. */
const sinSuscripcion = () => () => {};

type ReintentarPagoTarjetaProps = {
	orderId: string;
	channel: string;
	/** Si la orden ya quedó pagada, no hay nada que reintentar. */
	isPaid: boolean;
	browseLocale?: string;
};

/**
 * Reintento de pago con tarjeta de una orden B2B que quedó por pagar.
 *
 * Solo aparece cuando **esta misma sesión** creó la orden con tarjeta y el pago no
 * se completó (falla/anulación/timeout en Webpay): la recuperación desde cualquier
 * sesión (vista de orden) es Fase 2b. La orden existe y es un estado B2B legítimo;
 * reintentar vuelve a cobrar con Webpay sobre la misma orden.
 *
 * La marca vive en `sessionStorage`, así que el estado del servidor es «sin
 * reintento» (snapshot `false`) y recién en el navegador se decide si mostrarlo:
 * la hidratación coincide.
 */
export function ReintentarPagoTarjeta({ orderId, channel, isPaid, browseLocale }: ReintentarPagoTarjetaProps) {
	const pendiente = useSyncExternalStore(
		sinSuscripcion,
		() => isWebpayOrderPendingInSession(orderId),
		() => false,
	);
	const [enviando, setEnviando] = useState(false);
	const [error, setError] = useState("");

	// Si el pago entró (por este reintento o por otra vía), se olvida la marca.
	useEffect(() => {
		if (isPaid) {
			clearWebpayOrderPending(orderId);
		}
	}, [isPaid, orderId]);

	if (isPaid || !pendiente) {
		return null;
	}

	const reintentar = async () => {
		setEnviando(true);
		setError("");
		const pago = await executeWebpayOrderPayment({ orderId, channel, browseLocale });
		if (!pago.ok) {
			setError(pago.message);
			setEnviando(false);
			return;
		}
		// pago.ok: la pestaña está navegando a Webpay; se mantiene «enviando».
	};

	return (
		<div
			className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-500/40 dark:bg-amber-500/10"
			role="status"
			data-testid="reintentar-pago-tarjeta"
		>
			<AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
			<div className="flex-1 space-y-3">
				<div>
					<p className="text-sm font-medium text-foreground">El pago con tarjeta no se completó</p>
					<p className="text-sm text-muted-foreground">
						Tu pedido quedó registrado como pendiente de pago. Puedes reintentar el pago con Webpay.
					</p>
				</div>
				{error ? (
					<p className="text-sm text-destructive" role="alert">
						{error}
					</p>
				) : null}
				<Button type="button" onClick={() => void reintentar()} disabled={enviando} className="h-11 px-6">
					{enviando ? (
						<span className="flex items-center gap-2">
							<Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
							Redirigiendo a Webpay…
						</span>
					) : (
						"Reintentar pago"
					)}
				</Button>
			</div>
		</div>
	);
}
