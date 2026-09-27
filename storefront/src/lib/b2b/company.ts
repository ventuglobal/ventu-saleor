import "server-only";

import { cache } from "react";

import { errorDeAltaEmpresa, MENSAJE_ALTA_NO_DISPONIBLE } from "./errores";

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
	/**
	 * `sin_credito` | `no_operativo` | `pendiente_aprobacion` — por qué no se
	 * puede usar.
	 */
	motivo?: string;
};

/** `pendiente` mientras el equipo de Ventu no revise la empresa. */
export type EstadoEmpresa = "pendiente" | "aprobada";

export type Empresa = {
	registrada: true;
	/**
	 * ¿Ventu ya revisó la empresa y la habilitó para comprar en el canal B2B?
	 * Mientras no, ve el catálogo y sus tramos pero no puede hacer pedidos.
	 */
	aprobada: boolean;
	estado: EstadoEmpresa;
	rut: string;
	razon_social: string;
	nivel_precio: string;
	condicion_pago: string;
	credito_estado: string;
	medios_pago: MedioPago[];
};

export type SinEmpresa = {
	registrada: false;
	/**
	 * La App B2B no contestó: no se sabe si tiene empresa. Quien muestra algo
	 * según la empresa lo distingue para no pedirle «registra tu empresa» a una
	 * que ya lo hizo.
	 */
	error?: true;
};

export type ResultadoEmpresa = Empresa | SinEmpresa;

const SIN_EMPRESA: SinEmpresa = { registrada: false };
const EMPRESA_DESCONOCIDA: SinEmpresa = { registrada: false, error: true };

/** Igual que en la tabla de tramos: la App B2B complementa, no bloquea. */
const TIMEOUT_MS = 2500;

export function b2bBaseUrl(): string | null {
	return process.env.B2B_APP_URL?.replace(/\/$/, "") || null;
}

/**
 * Cabeceras de toda llamada del servidor a la App B2B.
 *
 * La App B2B entrega datos de empresas y crea pedidos por pagar; sin un secreto
 * compartido, cualquiera que conociera su URL podría hacerlo saltándose el
 * storefront. El token vive solo en el servidor —sin prefijo `NEXT_PUBLIC_`— y
 * debe ser el mismo `B2B_SERVICE_TOKEN` de ventu-b2b.
 *
 * Sin `B2B_APP_TOKEN` la cabecera se omite en vez de mandar `Bearer ` vacío: un
 * entorno local contra una App B2B que no exige token sigue funcionando, y uno
 * que sí lo exige responde 401, que queda registrado por `avisarSiRechazaToken`.
 * La autorización va al final para que `extra` no pueda pisarla.
 */
export function b2bHeaders(extra?: Record<string, string>): Record<string, string> {
	const token = process.env.B2B_APP_TOKEN?.trim();
	return token ? { ...extra, Authorization: `Bearer ${token}` } : { ...extra };
}

/**
 * Un 401 de la App B2B casi siempre es configuración —token ausente o distinto
 * del de ventu-b2b—, no algo del comprador. Se registra con una pista concreta
 * porque, de lo contrario, se vería solo como «sin empresa» o «sin tabla» y
 * costaría encontrarlo.
 */
export function avisarSiRechazaToken(res: Response, ruta: string): void {
	if (res.status !== 401) return;
	console.error(
		`La App B2B rechazó la llamada a ${ruta} (401). Revisa que B2B_APP_TOKEN coincida con B2B_SERVICE_TOKEN de ventu-b2b.`,
	);
}

type EmpresaSinNormalizar = Omit<Empresa, "aprobada" | "estado"> & { aprobada?: unknown };

function esEmpresa(dato: unknown): dato is EmpresaSinNormalizar {
	if (typeof dato !== "object" || dato === null) return false;
	const r = dato as Record<string, unknown>;
	return r.registrada === true && typeof r.rut === "string" && Array.isArray(r.medios_pago);
}

/**
 * La aprobación falla cerrada: sin `aprobada: true` explícito la empresa queda
 * en revisión. Una App B2B anterior a la aprobación no manda el campo, y leerlo
 * como aprobada habilitaría pedidos que nadie revisó.
 *
 * El estado se deriva de `aprobada` y no del `estado` que viene al lado, para
 * que ambos no puedan contradecirse. En revisión, los medios se marcan como no
 * disponibles aunque la App B2B no lo haya hecho.
 */
function normalizar(dato: EmpresaSinNormalizar): Empresa {
	const aprobada = dato.aprobada === true;
	return {
		...dato,
		aprobada,
		estado: aprobada ? "aprobada" : "pendiente",
		medios_pago: aprobada
			? dato.medios_pago
			: dato.medios_pago.map((m) => ({ ...m, habilitado: false, motivo: "pendiente_aprobacion" })),
	};
}

/**
 * La empresa asociada a un usuario, o `registrada: false`.
 *
 * Una App B2B caída no bloquea la tienda: se responde «sin empresa», marcado
 * con `error` para quien necesite distinguirlo.
 */
export async function getEmpresa(userId?: string | null): Promise<ResultadoEmpresa> {
	const base = b2bBaseUrl();
	if (!base || !userId) return SIN_EMPRESA;

	try {
		const res = await fetch(`${base}/company/de-usuario/${encodeURIComponent(userId)}`, {
			headers: b2bHeaders(),
			cache: "no-store",
			signal: AbortSignal.timeout(TIMEOUT_MS),
		});
		avisarSiRechazaToken(res, "/company/de-usuario");
		if (!res.ok) return EMPRESA_DESCONOCIDA;

		const dato: unknown = await res.json();
		if (esEmpresa(dato)) return normalizar(dato);
		// `{registrada: false}` es la respuesta normal de quien no tiene empresa;
		// cualquier otra forma es una App B2B que no entendemos.
		return (dato as { registrada?: unknown } | null)?.registrada === false
			? SIN_EMPRESA
			: EMPRESA_DESCONOCIDA;
	} catch {
		return EMPRESA_DESCONOCIDA;
	}
}

/**
 * `getEmpresa` una vez por petición. El menú de la cuenta, el aviso de empresa
 * y la página `/empresa` preguntan por el mismo usuario en el mismo render; sin
 * esto cada página del canal B2B repetiría la llamada a la App B2B.
 */
export const getEmpresaPorPeticion = cache(getEmpresa);

export type AltaEmpresa = {
	rut: string;
	razonSocial: string;
	giro?: string;
	telefono?: string;
};

export type ResultadoAlta =
	| { ok: true; rut: string }
	/** `mensaje` ya viene en castellano para quien compra; el detalle crudo queda en el log. */
	| { ok: false; status: number; mensaje: string; code?: string };

/**
 * Da de alta la empresa y la asocia al usuario.
 *
 * `userId` sale siempre del servidor: del `tokenCreate` del registro —que prueba
 * que quien llama conoce la contraseña— o de la sesión. Aceptarlo del cliente
 * permitiría asociar una empresa a la cuenta de otra persona.
 */
export async function registrarEmpresa(userId: string, datos: AltaEmpresa): Promise<ResultadoAlta> {
	const base = b2bBaseUrl();
	if (!base) {
		console.error("El alta de empresa no está disponible: falta B2B_APP_URL.");
		return { ok: false, status: 503, mensaje: MENSAJE_ALTA_NO_DISPONIBLE };
	}

	try {
		const res = await fetch(`${base}/company`, {
			method: "POST",
			headers: b2bHeaders({ "Content-Type": "application/json" }),
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

		avisarSiRechazaToken(res, "/company");
		if (res.status === 401) {
			// Es un problema nuestro de configuración; mostrarle «no autorizado» al
			// comprador lo haría pensar que el problema es su cuenta.
			return { ok: false, status: 503, mensaje: MENSAJE_ALTA_NO_DISPONIBLE };
		}

		// El motivo de la App B2B —dígito verificador, RUT ya registrado, usuario
		// que ya tiene empresa— decide qué mensaje ver, pero su texto va al log:
		// repite el RUT y el cálculo del verificador, y no le dice a quien compra
		// qué hacer.
		const cuerpo: unknown = await res.json().catch(() => null);
		console.warn(`(b2b) La App B2B rechazó el alta de empresa (${res.status}):`, JSON.stringify(cuerpo));
		const { mensaje, code } = errorDeAltaEmpresa(res.status, cuerpo);
		return { ok: false, status: res.status, mensaje, ...(code ? { code } : {}) };
	} catch (error) {
		console.error("(b2b) No se pudo llamar al alta de empresa:", error instanceof Error ? error.name : error);
		return { ok: false, status: 503, mensaje: MENSAJE_ALTA_NO_DISPONIBLE };
	}
}
