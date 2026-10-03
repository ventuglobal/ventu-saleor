/**
 * Shared pricing utilities for discount calculations.
 * Used by PDP, PLP, variant selection, cart, and other pricing-related components.
 *
 * SINGLE SOURCE OF TRUTH for all discount/sale detection logic.
 */

export interface PriceInfo {
	amount?: number | null;
	currency?: string | null;
}

export interface DiscountInfo {
	isOnSale: boolean;
	discountPercent: number | null;
}

/**
 * Con qué precio de un `TaxedMoney` se muestra la tienda: los canales B2B
 * muestran neto (sin IVA) y el resto sigue con el bruto de siempre. Se decide
 * en el servidor (ver `baseDePrecio` en `lib/b2b/canales.ts`) y llega a los
 * componentes cliente ya resuelta.
 */
export type BaseDePrecio = "net" | "gross";

export function baseDePrecioDe(precioNeto: boolean): BaseDePrecio {
	return precioNeto ? "net" : "gross";
}

type MontoConImpuesto<T> = { gross: T; net?: T | null };

/**
 * El precio a mostrar según la base. Si la consulta no trajo `net`, cae al
 * bruto: mejor un precio con IVA que un hueco.
 */
export function elegirPrecio<T>(precio: MontoConImpuesto<T>, base: BaseDePrecio): T;
export function elegirPrecio<T>(
	precio: MontoConImpuesto<T> | null | undefined,
	base: BaseDePrecio,
): T | undefined;
export function elegirPrecio<T>(
	precio: MontoConImpuesto<T> | null | undefined,
	base: BaseDePrecio,
): T | undefined {
	if (!precio) return undefined;
	return base === "net" ? (precio.net ?? precio.gross) : precio.gross;
}

type MontoDeRango = { amount?: number | null } | null;

export interface PriceRange {
	start?: { gross?: MontoDeRango; net?: MontoDeRango } | null;
	stop?: { gross?: MontoDeRango; net?: MontoDeRango } | null;
}

/**
 * Check if a price pair represents a discount.
 * Uses typeof to handle $0 prices correctly (0 is falsy in JS).
 */
export function hasDiscount(
	currentPrice: number | null | undefined,
	undiscountedPrice: number | null | undefined,
): boolean {
	return (
		typeof undiscountedPrice === "number" &&
		typeof currentPrice === "number" &&
		undiscountedPrice > currentPrice
	);
}

/**
 * Calculate discount percentage from price and undiscounted price.
 * Returns 0 if no discount or invalid prices.
 */
export function calculateDiscountPercent(
	currentPrice: number | null | undefined,
	undiscountedPrice: number | null | undefined,
): number {
	if (!hasDiscount(currentPrice, undiscountedPrice)) return 0;
	// TypeScript knows these are numbers after hasDiscount check
	return Math.round(((undiscountedPrice! - currentPrice!) / undiscountedPrice!) * 100);
}

/**
 * Get complete discount info from pricing data.
 * Useful for components that need both the flag and percentage.
 */
export function getDiscountInfo(
	currentPrice: number | null | undefined,
	undiscountedPrice: number | null | undefined,
): DiscountInfo {
	const isOnSale = hasDiscount(currentPrice, undiscountedPrice);
	const discountPercent = isOnSale ? calculateDiscountPercent(currentPrice, undiscountedPrice) : null;
	return { isOnSale, discountPercent };
}

/**
 * Get max discount info across a list of items with pricing.
 * Useful for showing "up to X% off" on variant options.
 */
export function getMaxDiscountInfo<T>(
	items: T[],
	getPrices: (item: T) => { current: number | null | undefined; undiscounted: number | null | undefined },
): DiscountInfo {
	let hasAnyDiscount = false;
	let maxPercent = 0;

	for (const item of items) {
		const { current, undiscounted } = getPrices(item);
		if (hasDiscount(current, undiscounted)) {
			hasAnyDiscount = true;
			const percent = calculateDiscountPercent(current, undiscounted);
			if (percent > maxPercent) maxPercent = percent;
		}
	}

	return {
		isOnSale: hasAnyDiscount,
		discountPercent: hasAnyDiscount ? maxPercent : null,
	};
}

/**
 * Check if ANY variant in a product is on sale using price ranges.
 *
 * For PLP product cards where we only have aggregated price ranges (not per-variant pricing).
 * Checks both start (cheapest) and stop (most expensive) to catch discounts on any variant.
 *
 * @example
 * // Variant A: $50 -> $30 (on sale), Variant B: $20 -> $20 (not on sale)
 * // priceRange: { start: $20, stop: $30 }
 * // priceRangeUndiscounted: { start: $20, stop: $50 }
 * // Result: true (because stop shows a discount)
 */
export function hasDiscountInPriceRange(
	priceRange: PriceRange | null | undefined,
	priceRangeUndiscounted: PriceRange | null | undefined,
	base: BaseDePrecio = "gross",
): boolean {
	const monto = (punta: PriceRange["start"]) =>
		(base === "net" ? (punta?.net ?? punta?.gross) : punta?.gross)?.amount;
	const startPrice = monto(priceRange?.start);
	const stopPrice = monto(priceRange?.stop);
	const undiscountedStart = monto(priceRangeUndiscounted?.start);
	const undiscountedStop = monto(priceRangeUndiscounted?.stop);

	// Check if cheapest variant is on sale
	const hasStartDiscount = hasDiscount(startPrice, undiscountedStart);
	// Check if most expensive variant is on sale
	const hasStopDiscount = hasDiscount(stopPrice, undiscountedStop);

	return hasStartDiscount || hasStopDiscount;
}
