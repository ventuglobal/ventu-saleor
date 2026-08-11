import { afterEach, describe, expect, it } from "vitest";

import { nombresDeCookieDeSesion, requiereSesion } from "./puerta";

afterEach(() => {
	delete process.env.B2B_CHANNELS;
});

describe("requiereSesion", () => {
	it("sin canales configurados no cierra nada", () => {
		expect(requiereSesion("b2b-cl", ["products"])).toBe(false);
	});

	it("cierra el catálogo del canal mayorista", () => {
		process.env.B2B_CHANNELS = "b2b-cl";
		expect(requiereSesion("b2b-cl", [])).toBe(true);
		expect(requiereSesion("b2b-cl", ["products"])).toBe(true);
		expect(requiereSesion("b2b-cl", ["products", "cable-usb"])).toBe(true);
		expect(requiereSesion("b2b-cl", ["categories", "electricidad"])).toBe(true);
	});

	it("no cierra el canal retail", () => {
		process.env.B2B_CHANNELS = "b2b-cl";
		expect(requiereSesion("retail-cl", ["products"])).toBe(false);
	});

	it("deja abiertas las rutas por donde se consigue la sesión", () => {
		// Cerrarlas sería un ciclo: para entrar hay que iniciar sesión, y para
		// iniciar sesión habría que haber entrado.
		process.env.B2B_CHANNELS = "b2b-cl";
		for (const ruta of ["login", "signup", "empresa", "reset-password", "set-password"]) {
			expect(requiereSesion("b2b-cl", [ruta])).toBe(false);
		}
	});
});

describe("nombresDeCookieDeSesion", () => {
	it("replica los nombres del SDK de autenticación", () => {
		expect(nombresDeCookieDeSesion("https://api.test/graphql/")).toEqual([
			"https://api.test/graphql/+saleor_auth_access_token",
			"https://api.test/graphql/+saleor_auth_module_refresh_token",
		]);
	});
});
