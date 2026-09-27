/**
 * Qué datos de empresa exige el registro según el canal.
 *
 * En un canal de empresa se compra con RUT, así que la cuenta nace con su
 * empresa. En un canal retail el RUT sobra: pedirlo espanta a quien compra para
 * su casa, y enviarlo asociaría una empresa que nadie pidió.
 *
 * Es una función pura, sin sesión ni red, porque la usan el formulario (en el
 * navegador) y la ruta de registro (en el servidor): la regla queda escrita una
 * sola vez. Quién es canal de empresa lo decide el servidor con `esCanalB2B` —
 * `B2B_CHANNELS` no llega al navegador— y el formulario recibe ese booleano.
 */

export type EmpresaDelRegistro =
	/** `empresa: null` = canal retail; no se registra empresa. */
	{ ok: true; empresa: { rut: string; razonSocial: string } | null } | { ok: false };

export function empresaDelRegistro(
	esB2B: boolean,
	rut?: string | null,
	razonSocial?: string | null,
): EmpresaDelRegistro {
	if (!esB2B) return { ok: true, empresa: null };

	const r = rut?.trim();
	const rs = razonSocial?.trim();
	if (!r || !rs) return { ok: false };

	return { ok: true, empresa: { rut: r, razonSocial: rs } };
}
