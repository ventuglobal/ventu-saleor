import { describe, expect, it } from "vitest";

import { baseDePrecioDe, elegirPrecio, hasDiscountInPriceRange } from "./pricing";

const clp = (amount: number) => ({ amount, currency: "CLP" });

describe("elegirPrecio", () => {
	const precio = { net: clp(10000), gross: clp(11900) };

	it("en B2B muestra el neto", () => {
		expect(elegirPrecio(precio, "net")).toEqual(clp(10000));
	});

	it("fuera de B2B sigue con el bruto", () => {
		expect(elegirPrecio(precio, "gross")).toEqual(clp(11900));
	});

	it("si la consulta no trajo el neto, cae al bruto", () => {
		expect(elegirPrecio({ gross: clp(11900) }, "net")).toEqual(clp(11900));
		expect(elegirPrecio({ gross: clp(11900), net: null }, "net")).toEqual(clp(11900));
	});

	it("sin precio no inventa uno", () => {
		expect(elegirPrecio(null, "net")).toBeUndefined();
		expect(elegirPrecio(undefined, "gross")).toBeUndefined();
	});
});

describe("baseDePrecioDe", () => {
	it("traduce el flag del canal a la base", () => {
		expect(baseDePrecioDe(true)).toBe("net");
		expect(baseDePrecioDe(false)).toBe("gross");
	});
});

describe("hasDiscountInPriceRange por base", () => {
	const rango = { start: { net: clp(9000), gross: clp(10710) }, stop: { net: clp(9000), gross: clp(10710) } };
	const sinDescuento = {
		start: { net: clp(10000), gross: clp(11900) },
		stop: { net: clp(10000), gross: clp(11900) },
	};

	it("detecta el descuento en neto y en bruto", () => {
		expect(hasDiscountInPriceRange(rango, sinDescuento, "net")).toBe(true);
		expect(hasDiscountInPriceRange(rango, sinDescuento)).toBe(true);
	});

	it("sin descuento no marca oferta", () => {
		expect(hasDiscountInPriceRange(sinDescuento, sinDescuento, "net")).toBe(false);
	});
});
