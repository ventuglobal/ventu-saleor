"use client";

import { createContext, type ReactNode, use } from "react";

/**
 * ¿El checkout pertenece a un canal de empresa?
 *
 * Lo decide el servidor con `B2B_CHANNELS`, que no llega al navegador, y aquí
 * solo viaja el booleano. Sin proveedor vale `false`: el checkout retail es el
 * comportamiento por omisión, así que un montaje que no lo declare nunca
 * ofrece el pedido por pagar.
 */
const CheckoutCanalB2BContext = createContext(false);

type CheckoutCanalB2BProviderProps = {
	canalB2B: boolean;
	children: ReactNode;
};

export function CheckoutCanalB2BProvider({ canalB2B, children }: CheckoutCanalB2BProviderProps) {
	return <CheckoutCanalB2BContext value={canalB2B}>{children}</CheckoutCanalB2BContext>;
}

export function useCheckoutCanalB2B(): boolean {
	return use(CheckoutCanalB2BContext);
}
