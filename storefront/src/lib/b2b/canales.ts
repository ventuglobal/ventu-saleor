import { type BaseDePrecio, baseDePrecioDe } from "@/lib/pricing";

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
 * Los canales B2B muestran precios netos (sin IVA); el resto, con IVA. Solo en
 * el servidor: `B2B_CHANNELS` no llega al navegador, así que a los componentes
 * cliente se les pasa el resultado como prop.
 */
export function baseDePrecio(channel: string): BaseDePrecio {
	return baseDePrecioDe(esCanalB2B(channel));
}
