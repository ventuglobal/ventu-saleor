"use client";

import { Suspense } from "react";
import { ErrorBoundary } from "react-error-boundary";

import type { CheckoutUser, ServerOrder } from "@/checkout/lib/checkout-types";
import { CheckoutBrowseProvider } from "@/checkout/providers/checkout-browse";
import { OrderDataProvider } from "@/checkout/providers/order-data";
import { CheckoutUserProvider } from "@/checkout/providers/checkout-user";
import { CheckoutCanalB2BProvider } from "@/checkout/providers/checkout-canal-b2b";
import { OrderConfirmation, OrderConfirmationSkeleton } from "@/checkout/views/order-confirmation";
import { CheckoutCrashFallback } from "@/checkout/views/page-not-found";
import "./index.css";

import type { LocaleSlug } from "@/config/locale";
import type { CheckoutMessages } from "@/i18n/load-messages";
import { CheckoutIntlProvider } from "@/checkout/providers/checkout-intl";

type OrderConfirmationAppProps = {
	orderId: string | null;
	initialOrder: ServerOrder | null;
	initialUser: CheckoutUser | null;
	storefrontLocale: LocaleSlug;
	messages: CheckoutMessages;
	/** Lo decide el servidor con el canal de la orden: en B2B el resumen va neto. */
	canalB2B?: boolean;
};

/**
 * Client shell for order confirmation — separate from active checkout (`CheckoutApp`).
 */
export function OrderConfirmationApp({
	orderId,
	initialOrder,
	initialUser,
	storefrontLocale,
	messages,
	canalB2B = false,
}: OrderConfirmationAppProps) {
	return (
		<CheckoutIntlProvider locale={storefrontLocale} messages={messages}>
			<CheckoutBrowseProvider locale={storefrontLocale}>
				<CheckoutUserProvider initialUser={initialUser}>
					<OrderDataProvider orderId={orderId} initialOrder={initialOrder}>
						<CheckoutCanalB2BProvider canalB2B={canalB2B}>
							<ErrorBoundary FallbackComponent={CheckoutCrashFallback}>
								<Suspense fallback={<OrderConfirmationSkeleton />}>
									<OrderConfirmation />
								</Suspense>
							</ErrorBoundary>
						</CheckoutCanalB2BProvider>
					</OrderDataProvider>
				</CheckoutUserProvider>
			</CheckoutBrowseProvider>
		</CheckoutIntlProvider>
	);
}
