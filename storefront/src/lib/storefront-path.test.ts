import { beforeAll, describe, expect, it, vi } from "vitest";

// El mercado por defecto (locale + channel) define qué URLs viven en la raíz,
// así que se fija antes de importar el módulo: ambos se leen de `process.env`
// en tiempo de import.
vi.stubEnv("NEXT_PUBLIC_DEFAULT_CHANNEL", "retail-cl");
vi.stubEnv("NEXT_PUBLIC_DEFAULT_LOCALE", "es");
vi.stubEnv("NEXT_PUBLIC_STOREFRONT_LOCALES", "es,en");

type PathModule = typeof import("./storefront-path");
let mod: PathModule;

beforeAll(async () => {
	mod = await import("./storefront-path");
});

describe("storefront-path", () => {
	it("sirve el mercado por defecto en la raíz (paridad de URLs con el sitio actual)", () => {
		expect(mod.buildStorefrontPath("es", "retail-cl")).toBe("/");
		expect(mod.buildStorefrontPath("es", "retail-cl", "/products/hoodie")).toBe("/products/hoodie");
	});

	it("mantiene el prefijo explícito para los demás mercados", () => {
		expect(mod.buildStorefrontPath("en", "uk")).toBe("/en/uk");
		expect(mod.buildStorefrontPath("en", "uk", "/products/hoodie")).toBe("/en/uk/products/hoodie");
	});

	it("parsea la forma prefijada", () => {
		expect(mod.parseStorefrontPathname("/en/uk/products/hoodie")).toEqual({
			locale: "en",
			channel: "uk",
			suffix: "/products/hoodie",
		});
		expect(mod.parseStorefrontPathname("/en/uk")).toEqual({
			locale: "en",
			channel: "uk",
			suffix: "",
		});
	});

	it("parsea la forma corta como el mercado por defecto", () => {
		// Sin esto `/products/hoodie` se leería como locale=products, channel=hoodie.
		expect(mod.parseStorefrontPathname("/products/hoodie")).toEqual({
			locale: "es",
			channel: "retail-cl",
			suffix: "/products/hoodie",
		});
		expect(mod.parseStorefrontPathname("/")).toEqual({
			locale: "es",
			channel: "retail-cl",
			suffix: "",
		});
	});

	it("cambia de channel conservando locale y sufijo", () => {
		expect(mod.replaceStorefrontChannel("/en/uk/products/hoodie", "us")).toBe("/en/us/products/hoodie");
		// Desde la forma corta hacia otro mercado: aparece el prefijo.
		expect(mod.replaceStorefrontChannel("/products/hoodie", "uk")).toBe("/es/uk/products/hoodie");
	});

	it("cambia de locale conservando channel y sufijo", () => {
		expect(mod.replaceStorefrontLocale("/en/uk/products/hoodie", "pl")).toBe("/pl/uk/products/hoodie");
		// Volver al mercado por defecto devuelve la URL a la raíz.
		expect(mod.replaceStorefrontLocale("/en/retail-cl/products", "es")).toBe("/products");
	});

	it("quita el prefijo locale/channel", () => {
		expect(mod.stripStorefrontPrefix("/en/uk/products", "en", "uk")).toBe("/products");
		expect(mod.stripStorefrontPrefix("/en/uk", "en", "uk")).toBe("/");
		// La forma corta ya viene sin prefijo y se devuelve intacta.
		expect(mod.stripStorefrontPrefix("/products", "es", "retail-cl")).toBe("/products");
	});
});
