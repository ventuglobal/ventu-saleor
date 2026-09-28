/**
 * Textos de error para quien compra en los caminos B2B.
 *
 * Saleor y la App B2B contestan con códigos (`INSUFFICIENT_STOCK`) o con textos
 * pensados para el log («dígito verificador incorrecto en '…'»). Ninguno le dice
 * a quien compra qué hacer, y algunos muestran detalles internos. Aquí se
 * traducen a un mensaje en castellano con el paso siguiente; el error crudo se
 * queda en el log del servidor.
 *
 * Módulo puro —sin red ni `server-only`— para probarlo solo y para que el
 * checkout, que corre en el navegador, use los mismos textos que las rutas.
 */

/** Cuando no se sabe qué pasó: mejor un «intenta de nuevo» que un texto interno. */
export const MENSAJE_GENERICO = "No pudimos completar la operación. Intenta de nuevo en unos minutos.";

/**
 * El texto exacto que usa la App B2B en el 403 de `/pedido`. Se comparte con el
 * checkout para que diga lo mismo antes de intentar el pedido y después.
 */
export const EMPRESA_EN_REVISION =
	"Tu empresa está en revisión. Te avisaremos cuando esté habilitada para comprar.";

/**
 * Códigos propios que el storefront le entrega al navegador junto al mensaje. El
 * checkout los usa para cambiar de estado —p. ej. dejar de ofrecer el botón si
 * la empresa volvió a revisión— sin interpretar textos.
 */
export const CODIGO_EN_REVISION = "PENDIENTE_APROBACION";
export const CODIGO_SIN_EMPRESA = "SIN_EMPRESA";
export const CODIGO_RUT_INVALIDO = "RUT_INVALIDO";

export const MENSAJE_PEDIDO_GENERICO = "No pudimos crear el pedido. Intenta de nuevo en unos minutos.";

const SIN_EMPRESA_PEDIDO =
	"Tu cuenta todavía no tiene una empresa registrada. Regístrala para poder comprar.";

/**
 * Códigos de `orderCreateFromCheckout` (Saleor 3.23) que puede provocar el
 * carrito de quien compra. Los que no están aquí caen al mensaje genérico.
 */
const PEDIDO_SALEOR: Readonly<Record<string, string>> = {
	INSUFFICIENT_STOCK:
		"Uno o más productos ya no tienen stock suficiente. Ajusta las cantidades del carrito e intenta de nuevo.",
	UNAVAILABLE_VARIANT_IN_CHANNEL:
		"Uno o más productos del carrito ya no están disponibles. Quítalos del carrito e intenta de nuevo.",
	SHIPPING_METHOD_NOT_SET: "Elige un método de despacho antes de realizar el pedido.",
	INVALID_SHIPPING_METHOD:
		"El método de despacho elegido ya no está disponible para este carrito. Elige otro.",
	SHIPPING_ADDRESS_NOT_SET: "Falta la dirección de despacho. Complétala antes de realizar el pedido.",
	BILLING_ADDRESS_NOT_SET: "Falta la dirección de facturación. Complétala antes de realizar el pedido.",
	EMAIL_NOT_SET: "Falta el correo de contacto del pedido. Revisa tus datos e intenta de nuevo.",
	NO_LINES: "Tu carrito está vacío. Agrega productos antes de realizar el pedido.",
	CHANNEL_INACTIVE: "La tienda no está recibiendo pedidos en este momento. Intenta más tarde.",
	VOUCHER_NOT_APPLICABLE: "El cupón de descuento ya no aplica a este carrito. Quítalo e intenta de nuevo.",
	GIFT_CARD_NOT_APPLICABLE: "La gift card ya no aplica a este carrito. Quítala e intenta de nuevo.",
	TAX_ERROR: "No pudimos calcular los impuestos del pedido. Intenta de nuevo en unos minutos.",
	// Saleor borra el carrito al crear la orden: un carrito que ya no existe
	// suele ser un pedido que sí se creó en un intento anterior.
	CHECKOUT_NOT_FOUND:
		"No encontramos tu carrito. Si ya realizaste el pedido, revísalo en «Mis pedidos» antes de intentarlo de nuevo.",
	GRAPHQL_ERROR: MENSAJE_PEDIDO_GENERICO,
};

/**
 * Códigos propios de `/pedido` en la App B2B que piden algo concreto a quien
 * compra y que ningún status distingue por sí solo. Van aparte de los de Saleor
 * para que la búsqueda de códigos dentro de textos crudos siga limitada a Saleor.
 */
const PEDIDO_APP: Readonly<Record<string, string>> = {
	// La App B2B copia la dirección de despacho como facturación y Saleor la
	// rechazó. La dirección sí existe: decir que falta mandaría a buscarla.
	BILLING_ADDRESS_INVALID:
		"No pudimos usar tu dirección de despacho como dirección de facturación. Revísala e intenta de nuevo.",
	// Mismo código para dos casos: cambió la cantidad de un producto con precio
	// negociado, o el carrito cambió mientras se confirmaba. Sin esta entrada
	// caería en el 409 genérico, que culpa al medio de pago.
	CARRITO_MODIFICADO:
		"Tu carrito cambió. Revísalo e intenta de nuevo; si un producto tiene precio acordado con tu ejecutivo, vuelve a la cantidad acordada o pídele un carrito nuevo.",
};

/** Un error de la App B2B, ya separado en su texto y su código. */
type Crudo = { texto: string; codigo?: string };

/**
 * Lee `{detail, code}` —la forma de error de la App B2B— y también la que deja
 * FastAPI cuando el `detail` de la excepción es un objeto (`{detail: {detail,
 * code}}`). Un `detail` de lista (validación de FastAPI) no trae nada útil para
 * quien compra y queda vacío.
 */
function leerCrudo(cuerpo: unknown): Crudo {
	if (typeof cuerpo !== "object" || cuerpo === null) return { texto: "" };
	const r = cuerpo as Record<string, unknown>;
	const anidado =
		typeof r.detail === "object" && r.detail !== null && !Array.isArray(r.detail)
			? (r.detail as Record<string, unknown>)
			: null;

	const texto =
		typeof r.detail === "string"
			? r.detail
			: typeof anidado?.detail === "string"
				? anidado.detail
				: typeof anidado?.mensaje === "string"
					? anidado.mensaje
					: "";
	const codigo =
		typeof r.code === "string" ? r.code : typeof anidado?.code === "string" ? anidado.code : undefined;

	return { texto, codigo: codigo?.trim().toUpperCase() || undefined };
}

/**
 * Busca un código de Saleor dentro del texto. Es el caso de una App B2B que
 * todavía devuelve la lista de errores de Saleor como texto
 * (`[{'code': 'INSUFFICIENT_STOCK', …}]`) en vez de un `code` aparte. Si hay
 * varios, gana el primero que aparece.
 */
function codigoSaleorEnTexto(texto: string): string | undefined {
	let mejor: { codigo: string; posicion: number } | undefined;
	for (const codigo of Object.keys(PEDIDO_SALEOR)) {
		const posicion = texto.indexOf(codigo);
		if (posicion >= 0 && (!mejor || posicion < mejor.posicion)) mejor = { codigo, posicion };
	}
	return mejor?.codigo;
}

export type ErrorTraducido = {
	/** Lo que ve quien compra. */
	mensaje: string;
	/** Código estable para que el navegador decida qué mostrar, nunca el error crudo. */
	code?: string;
};

/**
 * Traduce un rechazo de `POST /pedido` de la App B2B.
 *
 * Primero el código (de Saleor o propio), después el status. Los textos que hoy
 * manda la App B2B sin código se reconocen solo para elegir entre dos mensajes
 * nuestros del mismo status; nunca se reenvían.
 */
export function errorDePedido(status: number, cuerpo: unknown): ErrorTraducido {
	const { texto, codigo: codigoDeclarado } = leerCrudo(cuerpo);
	const codigo = codigoDeclarado ?? codigoSaleorEnTexto(texto);

	if (codigo && Object.hasOwn(PEDIDO_SALEOR, codigo)) {
		return { mensaje: PEDIDO_SALEOR[codigo], code: codigo };
	}
	if (codigo && Object.hasOwn(PEDIDO_APP, codigo)) {
		return { mensaje: PEDIDO_APP[codigo], code: codigo };
	}
	if (codigo === CODIGO_EN_REVISION || texto === EMPRESA_EN_REVISION) {
		return { mensaje: EMPRESA_EN_REVISION, code: CODIGO_EN_REVISION };
	}
	if (codigo === CODIGO_SIN_EMPRESA) {
		return { mensaje: SIN_EMPRESA_PEDIDO, code: CODIGO_SIN_EMPRESA };
	}

	switch (status) {
		case 403:
			// Dos 403 posibles: sin empresa, o un carrito de otra cuenta (sesión
			// cambiada en otra pestaña). El segundo se arregla volviendo a entrar.
			return /empresa/i.test(texto)
				? { mensaje: SIN_EMPRESA_PEDIDO, code: CODIGO_SIN_EMPRESA }
				: { mensaje: "Este carrito no corresponde a tu sesión. Vuelve a iniciar sesión e intenta de nuevo." };
		case 404:
			return { mensaje: PEDIDO_SALEOR.CHECKOUT_NOT_FOUND };
		case 409:
			// El medio existe pero esta empresa no puede usarlo (p. ej. sin crédito).
			return { mensaje: "Este medio de pago no está disponible para tu empresa. Elige otro." };
		case 422:
			if (/direcci[oó]n/i.test(texto)) return { mensaje: PEDIDO_SALEOR.SHIPPING_ADDRESS_NOT_SET };
			if (/canal/i.test(texto)) return { mensaje: "Este carrito no admite pedidos de empresa." };
			return { mensaje: "No pudimos crear el pedido con este carrito. Revísalo e intenta de nuevo." };
		case 504:
			// Saleor pudo haber creado la orden igual: reintentar a ciegas la duplicaría.
			return {
				mensaje:
					"No recibimos la confirmación del pedido a tiempo. Revisa «Mis pedidos» antes de intentarlo de nuevo.",
			};
		default:
			return { mensaje: MENSAJE_PEDIDO_GENERICO };
	}
}

/** La App B2B no contestó al consultar la empresa: no culpar a quien compra. */
export const MENSAJE_EMPRESA_NO_DISPONIBLE =
	"No pudimos consultar los datos de tu empresa. Intenta de nuevo en unos minutos.";

export const MENSAJE_RUT_INVALIDO =
	"El RUT no es válido. Revisa el número y el dígito verificador (por ejemplo, 76.543.210-3).";

export const MENSAJE_ALTA_NO_DISPONIBLE =
	"El registro de empresas no está disponible en este momento. Intenta de nuevo en unos minutos.";

/**
 * Traduce un rechazo de `POST /company` de la App B2B.
 *
 * El detalle crudo repite el RUT digitado y el cálculo del dígito verificador:
 * útil en el log, confuso en pantalla.
 */
export function errorDeAltaEmpresa(status: number, cuerpo: unknown): ErrorTraducido {
	const { texto, codigo } = leerCrudo(cuerpo);

	if (codigo === CODIGO_RUT_INVALIDO) return { mensaje: MENSAJE_RUT_INVALIDO, code: CODIGO_RUT_INVALIDO };

	if (status === 422) {
		if (/raz[oó]n social/i.test(texto)) return { mensaje: "Ingresa la razón social de tu empresa." };
		if (/rut|verificador|largo|num[eé]rico/i.test(texto)) {
			return { mensaje: MENSAJE_RUT_INVALIDO, code: CODIGO_RUT_INVALIDO };
		}
		return { mensaje: "Revisa los datos de tu empresa e intenta de nuevo." };
	}
	if (status === 409) {
		// Dos conflictos distintos: esta cuenta ya tiene empresa, o el RUT ya es de
		// otra cuenta. Piden cosas distintas, así que se distinguen.
		return /usuario/i.test(texto)
			? {
					mensaje:
						"Tu cuenta ya tiene una empresa registrada. Si necesitas cambiar sus datos, escríbele al equipo de Ventu.",
				}
			: {
					mensaje:
						"Ese RUT ya está registrado en otra cuenta. Si es tu empresa, escríbele al equipo de Ventu.",
				};
	}
	if (status === 400) return { mensaje: "Revisa los datos de tu empresa e intenta de nuevo." };
	if (status === 401 || status >= 500) return { mensaje: MENSAJE_ALTA_NO_DISPONIBLE };
	return { mensaje: "No pudimos registrar la empresa. Intenta de nuevo en unos minutos." };
}

/**
 * Códigos de `accountRegister` (y los propios del registro) a castellano.
 *
 * El formulario traduce por código con sus propios textos por idioma; estos
 * son para cualquier otro cliente de la ruta y para que el `message` de la
 * respuesta nunca sea el texto en inglés de Saleor.
 */
const CUENTA: Readonly<Record<string, string>> = {
	UNIQUE: "Ya existe una cuenta con este correo. Inicia sesión o recupera tu contraseña.",
	INVALID: "Revisa el correo y los datos ingresados.",
	REQUIRED: "Completa los campos obligatorios.",
	PASSWORD_TOO_SHORT: "La contraseña es muy corta. Usa al menos 8 caracteres.",
	PASSWORD_TOO_COMMON: "Esa contraseña es muy común. Elige una más difícil de adivinar.",
	PASSWORD_ENTIRELY_NUMERIC: "La contraseña no puede tener solo números.",
	PASSWORD_TOO_SIMILAR: "La contraseña se parece demasiado a tus datos. Elige otra.",
	INVALID_PASSWORD: "La contraseña no cumple los requisitos. Elige otra.",
	EMPRESA_REQUERIDA: "Indica la razón social y el RUT de tu empresa.",
	[CODIGO_RUT_INVALIDO]: MENSAJE_RUT_INVALIDO,
};

export function mensajeDeCuenta(codigo?: string | null): string {
	const c = codigo?.trim().toUpperCase() ?? "";
	return Object.hasOwn(CUENTA, c)
		? CUENTA[c]
		: "No pudimos crear la cuenta. Revisa los datos e intenta de nuevo.";
}

/**
 * Qué decirle a quien se registró en un canal de empresa cuando la cuenta quedó
 * creada pero la empresa no. Es el caso normal mientras Saleor pida confirmar
 * el correo: sin confirmar no hay sesión, y sin sesión no se sabe a qué cuenta
 * asociar el RUT.
 */
export const EMPRESA_PENDIENTE_REGISTRO =
	"Tu cuenta quedó creada. Confirma tu correo, inicia sesión y completa los datos de tu empresa en «Registrar empresa».";

/**
 * El alta de empresa se intentó y la App B2B la rechazó (RUT inválido, RUT de
 * otra cuenta…). Primero el motivo, ya traducido; después el paso siguiente,
 * porque la cuenta sí quedó creada.
 */
export function empresaPendienteTrasRechazo(motivo: string): string {
	return `${motivo} Tu cuenta quedó creada: inicia sesión y completa los datos de tu empresa en «Registrar empresa».`;
}
