import { describe, expect, it } from "vitest";

import {
	CODIGO_EN_REVISION,
	CODIGO_SIN_EMPRESA,
	EMPRESA_EN_REVISION,
	MENSAJE_ALTA_NO_DISPONIBLE,
	MENSAJE_PEDIDO_GENERICO,
	MENSAJE_RUT_INVALIDO,
	errorDeAltaEmpresa,
	errorDePedido,
	mensajeDeCuenta,
} from "./errores";

/** Los códigos de `orderCreateFromCheckout` que puede provocar un carrito. */
const CODIGOS_PEDIDO = [
	"INSUFFICIENT_STOCK",
	"UNAVAILABLE_VARIANT_IN_CHANNEL",
	"SHIPPING_METHOD_NOT_SET",
	"SHIPPING_ADDRESS_NOT_SET",
	"BILLING_ADDRESS_NOT_SET",
	"EMAIL_NOT_SET",
	"NO_LINES",
	"CHANNEL_INACTIVE",
	"INVALID_SHIPPING_METHOD",
	"VOUCHER_NOT_APPLICABLE",
	"GIFT_CARD_NOT_APPLICABLE",
	"TAX_ERROR",
	"CHECKOUT_NOT_FOUND",
	"GRAPHQL_ERROR",
];

describe("errorDePedido", () => {
	it.each(CODIGOS_PEDIDO)("%s tiene un mensaje en castellano que no repite el código", (codigo) => {
		const r = errorDePedido(422, { detail: "Saleor rechazó la orden", code: codigo });

		expect(r.code).toBe(codigo);
		expect(r.mensaje).not.toContain(codigo);
		expect(r.mensaje).not.toBe("Saleor rechazó la orden");
		expect(r.mensaje.length).toBeGreaterThan(10);
	});

	it("el stock insuficiente pide ajustar el carrito", () => {
		expect(errorDePedido(409, { detail: "x", code: "INSUFFICIENT_STOCK" }).mensaje).toMatch(/stock/i);
	});

	it("lee el código anidado que deja FastAPI con un `detail` de objeto", () => {
		const r = errorDePedido(422, { detail: { detail: "sin stock", code: "INSUFFICIENT_STOCK" } });
		expect(r.code).toBe("INSUFFICIENT_STOCK");
	});

	it("acepta el código en minúsculas", () => {
		expect(errorDePedido(422, { detail: "x", code: "no_lines" }).code).toBe("NO_LINES");
	});

	it("reconoce un código de Saleor dentro del texto crudo, sin reenviar el texto", () => {
		// Es lo que manda hoy la App B2B: `str()` de la lista de errores.
		const crudo =
			"[{'field': 'lines', 'message': 'Insufficient product stock', 'code': 'INSUFFICIENT_STOCK'}]";
		const r = errorDePedido(422, { detail: crudo });

		expect(r.code).toBe("INSUFFICIENT_STOCK");
		expect(r.mensaje).not.toContain("Insufficient");
	});

	it("la empresa en revisión se reconoce por su código o por el texto exacto", () => {
		expect(errorDePedido(403, { detail: "otra cosa", code: "pendiente_aprobacion" })).toEqual({
			mensaje: EMPRESA_EN_REVISION,
			code: CODIGO_EN_REVISION,
		});
		expect(errorDePedido(403, { detail: EMPRESA_EN_REVISION })).toEqual({
			mensaje: EMPRESA_EN_REVISION,
			code: CODIGO_EN_REVISION,
		});
	});

	it("un 403 por falta de empresa se distingue del carrito ajeno", () => {
		expect(errorDePedido(403, { detail: "el usuario no tiene empresa asociada" }).code).toBe(
			CODIGO_SIN_EMPRESA,
		);

		const ajeno = errorDePedido(403, { detail: "el carrito no pertenece a este usuario" });
		expect(ajeno.code).toBeUndefined();
		expect(ajeno.mensaje).toMatch(/sesión/);
	});

	it("un medio no disponible (409) no reenvía el texto de la App B2B", () => {
		const r = errorDePedido(409, { detail: "Cheke Maxxa 30 días requiere crédito aprobado" });
		expect(r.mensaje).toMatch(/medio de pago/);
		expect(r.mensaje).not.toContain("Cheke");
	});

	it("la falta de dirección (422 sin código) pide la dirección de despacho", () => {
		expect(errorDePedido(422, { detail: "falta la dirección de despacho del pedido" }).mensaje).toMatch(
			/dirección de despacho/,
		);
	});

	it("una dirección de despacho que no sirve para facturar no se confunde con una que falta", () => {
		// Es el 422 que manda la App B2B cuando Saleor rechaza la copia de la
		// dirección de despacho como facturación: la dirección existe.
		const r = errorDePedido(422, {
			detail: "la dirección de despacho no sirve como dirección de facturación; revísala e intenta de nuevo",
			code: "BILLING_ADDRESS_INVALID",
		});

		expect(r.code).toBe("BILLING_ADDRESS_INVALID");
		expect(r.mensaje).toMatch(/facturación/);
		expect(r.mensaje).not.toMatch(/^Falta/);
	});

	it("un carrito modificado no se confunde con un medio de pago no disponible", () => {
		// Ambos son 409 en la App B2B; solo el código los distingue.
		const r = errorDePedido(409, {
			detail: "el carrito cambió mientras se confirmaba el pedido; revísalo e intenta de nuevo",
			code: "CARRITO_MODIFICADO",
		});

		expect(r.code).toBe("CARRITO_MODIFICADO");
		expect(r.mensaje).toMatch(/carrito cambió/);
		expect(r.mensaje).not.toMatch(/medio de pago/);
	});

	it("un timeout avisa que el pedido pudo haberse creado", () => {
		expect(errorDePedido(504, { detail: "Saleor no confirmó el pedido a tiempo" }).mensaje).toMatch(
			/Mis pedidos/,
		);
	});

	it("cualquier otra cosa cae al mensaje genérico", () => {
		expect(errorDePedido(500, "Internal Server Error")).toEqual({ mensaje: MENSAJE_PEDIDO_GENERICO });
		expect(errorDePedido(502, null)).toEqual({ mensaje: MENSAJE_PEDIDO_GENERICO });
		expect(errorDePedido(418, { detail: [{ loc: ["body"], msg: "field required" }] })).toEqual({
			mensaje: MENSAJE_PEDIDO_GENERICO,
		});
	});

	it("un código desconocido no se reenvía", () => {
		const r = errorDePedido(500, { detail: "x", code: "PERMISSION_DENIED" });
		expect(r).toEqual({ mensaje: MENSAJE_PEDIDO_GENERICO });
	});
});

describe("errorDeAltaEmpresa", () => {
	it.each([
		"RUT vacío",
		"largo inválido: '123'",
		"el cuerpo debe ser numérico: 'AB.CDE-1'",
		"dígito verificador incorrecto en '76.543.210-4': es 4, debería ser 3",
	])("«%s» es un RUT inválido", (detalle) => {
		expect(errorDeAltaEmpresa(422, { detail: detalle })).toEqual({
			mensaje: MENSAJE_RUT_INVALIDO,
			code: "RUT_INVALIDO",
		});
	});

	it("la razón social vacía pide la razón social", () => {
		expect(errorDeAltaEmpresa(422, { detail: "razón social vacía" }).mensaje).toMatch(/razón social/);
	});

	it("distingue la cuenta que ya tiene empresa del RUT ya registrado", () => {
		const propia = errorDeAltaEmpresa(409, {
			detail: "el usuario ya tiene una empresa registrada; los cambios los hace el equipo de Ventu",
		});
		const ajena = errorDeAltaEmpresa(409, { detail: "el RUT 76543210-3 ya está registrado" });

		expect(propia.mensaje).toMatch(/Tu cuenta ya tiene/);
		expect(ajena.mensaje).toMatch(/otra cuenta/);
		expect(ajena.mensaje).not.toContain("76543210");
	});

	it("un fallo del servicio no culpa a quien se registra", () => {
		expect(errorDeAltaEmpresa(502, { detail: "no se pudo completar la operación con Saleor" })).toEqual({
			mensaje: MENSAJE_ALTA_NO_DISPONIBLE,
		});
		expect(errorDeAltaEmpresa(401, { detail: "token de acceso inválido o ausente" })).toEqual({
			mensaje: MENSAJE_ALTA_NO_DISPONIBLE,
		});
	});
});

describe("mensajeDeCuenta", () => {
	it("traduce los códigos de Saleor a castellano", () => {
		expect(mensajeDeCuenta("PASSWORD_TOO_COMMON")).toMatch(/contraseña/);
		expect(mensajeDeCuenta("UNIQUE")).toMatch(/Ya existe una cuenta/);
		expect(mensajeDeCuenta("RUT_INVALIDO")).toBe(MENSAJE_RUT_INVALIDO);
	});

	it("un código desconocido o ausente cae al genérico", () => {
		expect(mensajeDeCuenta("ALGO_NUEVO")).toMatch(/No pudimos crear la cuenta/);
		expect(mensajeDeCuenta(null)).toMatch(/No pudimos crear la cuenta/);
		// Sin prototipo de por medio: `toString` no es un código.
		expect(mensajeDeCuenta("toString")).toMatch(/No pudimos crear la cuenta/);
	});
});
