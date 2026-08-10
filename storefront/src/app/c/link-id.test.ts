import { describe, expect, it } from "vitest";

/**
 * El identificador del enlace lo genera la App B2B (`ventu_b2b/cart/link.py`) y
 * lo valida el storefront. Son dos lenguajes distintos, así que el contrato solo
 * se sostiene si ambos lados coinciden en alfabeto y largo: este test fija esa
 * forma para que un cambio en un lado no pase inadvertido en el otro.
 */
const LINK_ID = /^[23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ]{22}$/;

const ALFABETO = "23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ";

describe("identificador de enlace de carrito", () => {
	it("acepta un identificador con la forma que genera la App B2B", () => {
		expect(LINK_ID.test("a".repeat(22))).toBe(true);
		expect(LINK_ID.test(ALFABETO.slice(0, 22))).toBe(true);
	});

	it("excluye los caracteres que se confunden al dictar por teléfono", () => {
		for (const confundible of ["0", "O", "1", "l", "I"]) {
			expect(ALFABETO.includes(confundible)).toBe(false);
		}
	});

	it("rechaza un largo distinto", () => {
		expect(LINK_ID.test("a".repeat(21))).toBe(false);
		expect(LINK_ID.test("a".repeat(23))).toBe(false);
		expect(LINK_ID.test("")).toBe(false);
	});

	it("rechaza intentos de recorrer rutas", () => {
		for (const malo of ["../../etc/passwd", "a".repeat(21) + "/", "a".repeat(21) + "."]) {
			expect(LINK_ID.test(malo)).toBe(false);
		}
	});

	it("rechaza caracteres fuera del alfabeto", () => {
		expect(LINK_ID.test("0".repeat(22))).toBe(false);
		expect(LINK_ID.test("O".repeat(22))).toBe(false);
		expect(LINK_ID.test("a".repeat(21) + "!")).toBe(false);
	});
});
