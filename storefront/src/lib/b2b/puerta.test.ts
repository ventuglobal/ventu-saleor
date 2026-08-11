import { afterEach, describe, expect, it } from "vitest";

import { haySesionEnCookies, requiereSesion } from "./puerta";

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

describe("haySesionEnCookies", () => {
	const API = "https://saleor-api-production-3f5f.up.railway.app/graphql/";

	// Nombres reales observados en producción: el SDK codifica el nombre y todo
	// lo que no es alfanumérico pasa a `_`. Armarlo a mano con la URL cruda no
	// encuentra nada, y la puerta rechazaría también a quien sí inició sesión.
	const ACCESO = "https___saleor-api-production-3f5f_up_railway_app_graphql__saleor_auth_access_token";
	const REFRESCO =
		"https___saleor-api-production-3f5f_up_railway_app_graphql__saleor_auth_module_refresh_token";

	it("reconoce la cookie de acceso que emite el SDK", () => {
		expect(haySesionEnCookies([{ name: ACCESO }], API)).toBe(true);
	});

	it("le basta el token de refresco", () => {
		// El de acceso caduca antes; con el de refresco la sesión se recupera sola.
		expect(haySesionEnCookies([{ name: REFRESCO }], API)).toBe(true);
	});

	it("sin cookies no hay sesión", () => {
		expect(haySesionEnCookies([], API)).toBe(false);
		expect(haySesionEnCookies([{ name: "otra_cosa" }], API)).toBe(false);
	});

	it("ignora la cookie de estado, que no es un token", () => {
		expect(
			haySesionEnCookies(
				[
					{
						name: "https___saleor-api-production-3f5f_up_railway_app_graphql__saleor_auth_module_auth_state",
					},
				],
				API,
			),
		).toBe(false);
	});

	it("ignora tokens de otra instancia de Saleor", () => {
		// Darlos por buenos reportaría una sesión que esta API rechaza siempre.
		expect(
			haySesionEnCookies([{ name: "https___otra_api_test_graphql__saleor_auth_access_token" }], API),
		).toBe(false);
	});
});
