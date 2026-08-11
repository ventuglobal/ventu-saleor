/**
 * Qué canales exigen empresa registrada.
 *
 * Vive aparte de `gate.ts` porque es una decisión de configuración pura, sin
 * sesión ni red: así se puede probar y usar sin arrastrar el resto.
 */

/** Vacío = ningún canal exige empresa, y la tienda se comporta como antes. */
export function esCanalB2B(channel: string): boolean {
	return (process.env.B2B_CHANNELS ?? "")
		.split(",")
		.map((c) => c.trim())
		.filter(Boolean)
		.includes(channel);
}
