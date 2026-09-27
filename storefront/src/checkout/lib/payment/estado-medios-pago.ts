import { CODIGO_EN_REVISION, CODIGO_SIN_EMPRESA } from "@/lib/b2b/errores";

/**
 * Qué muestra la caja de medios de pago en un canal de empresa.
 *
 * En un canal B2B las pasarelas de Saleor no se ofrecen nunca: un pedido
 * mayorista se cierra contra una promesa de pago, no contra una tarjeta. Así
 * que esta caja es lo único que hay en el paso de pago, y en cada estado dice
 * qué falta para poder comprar en vez de quedar vacía.
 *
 * Función pura, separada del componente, para probar la elección de estado sin
 * montar el checkout.
 */

export type MedioPago = {
	codigo: string;
	etiqueta: string;
	diferido: boolean;
	habilitado: boolean;
	motivo?: string;
};

export type DatosEmpresa = {
	razon_social?: string;
	rut?: string;
	medios_pago: MedioPago[];
};

export type EstadoMediosPago =
	/** Sin sesión: primero iniciar sesión, porque la empresa va con la cuenta. */
	| { tipo: "invitado" }
	/** Con sesión y sin empresa: registrarla en /empresa. */
	| { tipo: "sin_empresa" }
	/** Empresa registrada que Ventu todavía no aprueba: sin botón de pedido. */
	| { tipo: "en_revision"; empresa: DatosEmpresa }
	/** Aprobada: los medios de pago, como siempre. */
	| { tipo: "aprobada"; empresa: DatosEmpresa }
	/** Aprobada pero la App B2B no le ofrece ningún medio. */
	| { tipo: "sin_medios"; empresa: DatosEmpresa }
	/** No se pudo saber: la App B2B o la sesión no contestaron. */
	| { tipo: "error" };

function esMedio(dato: unknown): dato is MedioPago {
	if (typeof dato !== "object" || dato === null) return false;
	const m = dato as Record<string, unknown>;
	return typeof m.codigo === "string" && typeof m.etiqueta === "string";
}

function texto(valor: unknown): string | undefined {
	return typeof valor === "string" ? valor : undefined;
}

/**
 * Estado a partir de la respuesta de `GET /api/b2b/company`.
 *
 * La aprobación falla cerrada: sin `aprobada: true` explícito la empresa queda
 * en revisión, igual que en el servidor. Un medio sin `habilitado: true` queda
 * deshabilitado.
 */
export function estadoMediosPago(status: number, dato: unknown): EstadoMediosPago {
	if (status === 401) return { tipo: "invitado" };
	if (status < 200 || status >= 300 || typeof dato !== "object" || dato === null) return { tipo: "error" };

	const r = dato as Record<string, unknown>;

	if (r.registrada !== true) {
		if (r.registrada !== false) return { tipo: "error" };
		return r.autenticado === false ? { tipo: "invitado" } : { tipo: "sin_empresa" };
	}

	const aprobada = r.aprobada === true;
	const medios = Array.isArray(r.medios_pago) ? r.medios_pago.filter(esMedio) : [];
	const empresa: DatosEmpresa = {
		razon_social: texto(r.razon_social),
		rut: texto(r.rut),
		medios_pago: medios.map((m) => ({ ...m, habilitado: aprobada && m.habilitado === true })),
	};

	if (!aprobada) return { tipo: "en_revision", empresa };
	if (!empresa.medios_pago.length) return { tipo: "sin_medios", empresa };
	return { tipo: "aprobada", empresa };
}

/**
 * Si un rechazo de `POST /api/b2b/pedido` cambia lo que hay que mostrar.
 *
 * La empresa pudo volver a revisión, o la sesión expirar, entre que se cargó la
 * caja y se pidió el pedido. En esos casos dejar el botón sería invitar a
 * reintentar algo que va a fallar igual. `null` = el estado sigue; solo se
 * muestra el mensaje.
 */
export function estadoTrasRechazoDePedido(
	actual: EstadoMediosPago,
	status: number,
	code?: string,
): EstadoMediosPago | null {
	if (status === 401) return { tipo: "invitado" };
	if (code === CODIGO_SIN_EMPRESA) return { tipo: "sin_empresa" };
	if (code === CODIGO_EN_REVISION) {
		const empresa = "empresa" in actual ? actual.empresa : { medios_pago: [] };
		return {
			tipo: "en_revision",
			empresa: { ...empresa, medios_pago: empresa.medios_pago.map((m) => ({ ...m, habilitado: false })) },
		};
	}
	return null;
}

/** El primer medio usable: casi siempre hay uno solo y obligar a elegirlo no aporta. */
export function medioPreseleccionado(estado: EstadoMediosPago): string {
	return estado.tipo === "aprobada"
		? (estado.empresa.medios_pago.find((m) => m.habilitado)?.codigo ?? "")
		: "";
}
