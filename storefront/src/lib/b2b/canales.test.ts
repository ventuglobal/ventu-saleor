import { afterEach, describe, expect, it } from "vitest";

import { baseDePrecio, esCanalB2B } from "./canales";

afterEach(() => {
	delete process.env.B2B_CHANNELS;
});

describe("baseDePrecio", () => {
	it("los canales B2B muestran neto", () => {
		process.env.B2B_CHANNELS = "b2b-cl, mayorista";
		expect(esCanalB2B("mayorista")).toBe(true);
		expect(baseDePrecio("b2b-cl")).toBe("net");
		expect(baseDePrecio("mayorista")).toBe("net");
	});

	it("el retail sigue con IVA", () => {
		process.env.B2B_CHANNELS = "b2b-cl";
		expect(baseDePrecio("default-channel")).toBe("gross");
	});

	it("sin B2B_CHANNELS ningún canal cambia", () => {
		expect(baseDePrecio("b2b-cl")).toBe("gross");
	});
});
