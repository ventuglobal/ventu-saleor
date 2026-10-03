"use client";

import { useCallback, useEffect, useState, type FC } from "react";
import { useSearchParams } from "next/navigation";
import { type CheckoutFragment } from "@/checkout/graphql";
import { Button } from "@/ui/components/ui/button";
import { LoadingSpinner } from "@/checkout/ui-kit/loading-spinner";
import { type CheckoutPriceChangeNotice } from "@/checkout/lib/payment/checkout-pay-amount";
import { subscribePaymentActivityReset } from "@/checkout/lib/payment/checkout-payment-completion";
import { useCheckoutData } from "@/checkout/providers/checkout-data";
import { formatMoneyWithFallback } from "@/checkout/lib/utils/money";
import { PaymentTrustSignals } from "@/checkout/components/payment/payment-trust-signals";
import { executeWebpayCheckoutPayment } from "./execute-webpay-checkout-payment";
import { type WebpayBillingContext } from "./webpay-billing-context";

type WebpayPaymentProps = {
	checkout: CheckoutFragment;
	gatewayName?: string | null;
	billing: WebpayBillingContext;
	onPaymentError: (message: string) => void;
	onBillingErrors: (errors: Record<string, string>, focusField?: string) => void;
	onPriceChangeNotice: (notice: CheckoutPriceChangeNotice) => void;
	onPaymentActivityChange?: (active: boolean) => void;
};

/**
 * Método de pago Webpay (Transbank) para retail. Renderiza su propio botón: al
 * pagar inicia la transacción en Saleor, guarda el contexto y redirige (auto-POST)
 * al formulario de Transbank. El commit/aprobación lo decide el servidor al volver.
 */
export const WebpayPayment: FC<WebpayPaymentProps> = ({
	checkout,
	billing,
	onPaymentError,
	onBillingErrors,
	onPriceChangeNotice,
	onPaymentActivityChange,
}) => {
	const { refreshCheckout } = useCheckoutData();
	const searchParams = useSearchParams();
	const [isLoading, setIsLoading] = useState(false);

	const resetActivity = useCallback(() => {
		setIsLoading(false);
		onPaymentActivityChange?.(false);
	}, [onPaymentActivityChange]);

	useEffect(() => subscribePaymentActivityReset(resetActivity), [resetActivity]);

	const total = checkout.totalPrice?.gross;
	const totalStr = formatMoneyWithFallback(total);
	const browseLocale = searchParams.get("locale") ?? undefined;

	const handlePay = async () => {
		onPaymentError("");
		setIsLoading(true);
		onPaymentActivityChange?.(true);

		const result = await executeWebpayCheckoutPayment({
			checkout,
			billing,
			refreshCheckout,
			browseLocale,
		});

		if (result.ok) {
			// La pestaña navega a Transbank: dejamos el estado "pagando" activo.
			return;
		}

		if (result.kind === "billing") {
			onBillingErrors(result.errors, result.focusField);
		} else if (result.kind === "price_change") {
			onPriceChangeNotice(result.notice);
		} else {
			onPaymentError(result.message);
		}

		setIsLoading(false);
		onPaymentActivityChange?.(false);
	};

	return (
		<div className="space-y-6">
			<p className="text-sm text-muted-foreground">
				Serás redirigido a Webpay para completar el pago de forma segura con tu tarjeta de crédito o
				débito. Al finalizar, volverás a la tienda.
			</p>
			<PaymentTrustSignals className="pt-1" />
			<Button
				type="button"
				className="h-12 w-full md:w-auto md:min-w-[200px]"
				disabled={isLoading}
				onClick={() => void handlePay()}
			>
				{isLoading ? (
					<span className="flex items-center justify-center gap-2">
						<LoadingSpinner />
						Redirigiendo a Webpay...
					</span>
				) : (
					`Pagar ${totalStr} con Webpay`
				)}
			</Button>
		</div>
	);
};
