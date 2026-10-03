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

/**
 * Canales donde se ofrece Webpay (Transbank).
 *
 * `NEXT_PUBLIC_*` para que el mismo helper sirva en cliente y servidor (el borde
 * de seguridad en las server actions usa además `WEBPAY_CHANNELS`, ver
 * `getWebpayChannelGuardError`). Default `retail-cl` para no abrir Webpay en B2B
 * por olvido de configuración.
 */
export function esCanalWebpay(channel: string): boolean {
	const configured = (process.env.NEXT_PUBLIC_WEBPAY_CHANNELS ?? "retail-cl")
		.split(",")
		.map((c) => c.trim())
		.filter(Boolean);
	return configured.includes(channel);
}
