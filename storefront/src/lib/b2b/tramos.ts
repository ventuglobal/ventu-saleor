import "server-only";

/**
 * Tabla de precios por volumen de la App B2B.
 *
 * La escalera vive en la metadata **privada** del producto en Saleor y solo la
 * lee la App B2B; el storefront nunca la consulta directamente. Así el navegador
 * recibe la tabla únicamente cuando la sesión corresponde a una empresa
 * registrada — que es la regla comercial: la política de descuentos por volumen
 * es información reservada, y de ella se deduce el margen.
 *
 * El endpoint responde 200 en todos los casos, también cuando decide no mostrar
 * nada. Un 403 le confirmaría a un cliente retail que existe una tabla que no
 * puede ver, y eso invita a buscarla sin aportarle nada.
 */

export type Tramo = {
	/** Cantidad mínima, inclusive, a partir de la cual rige el precio. */
	desde: number;
	precio_unitario: number;
};

export type TramosVisibles = {
	visible: true;
	rut: string;
	canal: string;
	tramos: Tramo[];
};

export type TramosOcultos = {
	visible: false;
	/** `sin_identificar` | `sin_empresa` | `sin_tramos` | `no_disponible` */
	motivo: string;
};

export type TramosResult = TramosVisibles | TramosOcultos;

/**
 * Presupuesto de espera. La tabla es un complemento de la ficha: si la App B2B
 * tarda, la página se sirve sin ella en vez de hacer esperar por un adorno.
 */
const TIMEOUT_MS = 2500;

const oculta = (motivo: string): TramosOcultos => ({ visible: false, motivo });

/** ¿La respuesta tiene la forma que esperamos? Un JSON ajeno no debe pintarse. */
function esValida(dato: unknown): dato is TramosResult {
	if (typeof dato !== "object" || dato === null) return false;
	const r = dato as Record<string, unknown>;
	if (r.visible === false) return typeof r.motivo === "string";
	if (r.visible !== true) return false;
	return (
		Array.isArray(r.tramos) &&
		r.tramos.length > 0 &&
		r.tramos.every(
			(t) =>
				typeof t === "object" &&
				t !== null &&
				Number.isFinite((t as Tramo).desde) &&
				Number.isFinite((t as Tramo).precio_unitario),
		)
	);
}

/**
 * Consulta la tabla de tramos para una variante.
 *
 * `userId` es el id de Saleor de la sesión, resuelto en el servidor: quien
 * decide si hay empresa detrás es la App B2B, no el navegador. Sin sesión se
 * consulta igual —la respuesta será `sin_identificar`— para que el motivo salga
 * de un solo lugar.
 */
export async function getTramos(variantId: string, userId?: string | null): Promise<TramosResult> {
	const base = process.env.B2B_APP_URL?.replace(/\/$/, "");
	// Sin App B2B configurada la tienda funciona igual, solo que sin tabla.
	if (!base) return oculta("no_disponible");
	if (!userId) return oculta("sin_identificar");

	const url = `${base}/tramos/${encodeURIComponent(variantId)}?user_id=${encodeURIComponent(userId)}`;

	try {
		const res = await fetch(url, {
			cache: "no-store",
			signal: AbortSignal.timeout(TIMEOUT_MS),
		});
		if (!res.ok) return oculta("no_disponible");

		const dato: unknown = await res.json();
		return esValida(dato) ? dato : oculta("no_disponible");
	} catch {
		// Timeout, DNS, App caída. La ficha se sirve sin tabla; nunca con un error.
		return oculta("no_disponible");
	}
}
