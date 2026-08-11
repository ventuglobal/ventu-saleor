import "server-only";

/**
 * Identidad empresarial: quién compra, en qué canal y con qué medios de pago.
 *
 * La empresa vive en la metadata privada del usuario en Saleor y solo la App
 * B2B la lee y la escribe. El storefront pregunta con el id de sesión resuelto
 * en el servidor — nunca con uno que venga del navegador, porque eso permitiría
 * pedir la empresa de otra persona.
 */

export type MedioPago = {
	codigo: string;
	etiqueta: string;
	/** El pedido nace por pagar en vez de pagado. */
	diferido: boolean;
	habilitado: boolean;
	/** `sin_credito` | `no_operativo` — por qué no se puede usar. */
	motivo?: string;
};

export type Empresa = {
	registrada: true;
	rut: string;
	razon_social: string;
	nivel_precio: string;
	condicion_pago: string;
	credito_estado: string;
	medios_pago: MedioPago[];
};

export type SinEmpresa = { registrada: false };

export type ResultadoEmpresa = Empresa | SinEmpresa;

const SIN_EMPRESA: SinEmpresa = { registrada: false };

/** Igual que en la tabla de tramos: la App B2B complementa, no bloquea. */
const TIMEOUT_MS = 2500;

export function b2bBaseUrl(): string | null {
	return process.env.B2B_APP_URL?.replace(/\/$/, "") || null;
}

function esEmpresa(dato: unknown): dato is Empresa {
	if (typeof dato !== "object" || dato === null) return false;
	const r = dato as Record<string, unknown>;
	return r.registrada === true && typeof r.rut === "string" && Array.isArray(r.medios_pago);
}

/** La empresa asociada a un usuario, o `registrada: false`. */
export async function getEmpresa(userId?: string | null): Promise<ResultadoEmpresa> {
	const base = b2bBaseUrl();
	if (!base || !userId) return SIN_EMPRESA;

	try {
		const res = await fetch(`${base}/company/de-usuario/${encodeURIComponent(userId)}`, {
			cache: "no-store",
			signal: AbortSignal.timeout(TIMEOUT_MS),
		});
		if (!res.ok) return SIN_EMPRESA;

		const dato: unknown = await res.json();
		return esEmpresa(dato) ? dato : SIN_EMPRESA;
	} catch {
		return SIN_EMPRESA;
	}
}

export type AltaEmpresa = {
	rut: string;
	razonSocial: string;
	giro?: string;
	telefono?: string;
};

export type ResultadoAlta = { ok: true; rut: string } | { ok: false; status: number; mensaje: string };

/**
 * Da de alta la empresa y la asocia al usuario.
 *
 * `userId` sale siempre del servidor: de la respuesta de `accountRegister` o de
 * la sesión. Aceptarlo del cliente permitiría asociar una empresa a la cuenta de
 * otra persona.
 */
export async function registrarEmpresa(userId: string, datos: AltaEmpresa): Promise<ResultadoAlta> {
	const base = b2bBaseUrl();
	if (!base) {
		return { ok: false, status: 503, mensaje: "El registro de empresas no está configurado." };
	}

	try {
		const res = await fetch(`${base}/company`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			cache: "no-store",
			signal: AbortSignal.timeout(TIMEOUT_MS * 2),
			body: JSON.stringify({
				user_id: userId,
				rut: datos.rut,
				razon_social: datos.razonSocial,
				giro: datos.giro ?? "",
				telefono: datos.telefono ?? "",
			}),
		});

		if (res.ok) {
			const dato = (await res.json()) as { rut?: string };
			return { ok: true, rut: dato.rut ?? datos.rut };
		}

		// La App B2B explica en castellano por qué rechazó el alta —RUT con dígito
		// verificador incorrecto, RUT ya registrado— y ese texto es más útil que
		// uno genérico.
		const cuerpo = (await res.json().catch(() => null)) as { detail?: string } | null;
		return { ok: false, status: res.status, mensaje: cuerpo?.detail || "No se pudo registrar la empresa." };
	} catch {
		return { ok: false, status: 503, mensaje: "El registro de empresas no está disponible." };
	}
}
