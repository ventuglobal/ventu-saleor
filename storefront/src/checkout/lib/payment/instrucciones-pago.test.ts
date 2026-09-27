import { afterEach, describe, expect, it, vi } from "vitest";

import { guardarInstruccionesPago, leerInstruccionesPago } from "./instrucciones-pago";

const PEDIDO = "T3JkZXI6MWYyYjNjNGQ=";

afterEach(() => {
	vi.unstubAllGlobals();
});

describe("instrucciones de pago", () => {
	it("la confirmación lee lo que dejó el pedido, saltos de línea incluidos", () => {
		const texto = "Banco Estado\nCuenta corriente 123456\nRUT 76.543.210-3";

		expect(guardarInstruccionesPago(PEDIDO, texto)).toBe(true);
		expect(leerInstruccionesPago(PEDIDO)).toBe(texto);
	});

	it("cada pedido tiene las suyas", () => {
		guardarInstruccionesPago(PEDIDO, "datos del primero");

		expect(leerInstruccionesPago("T3JkZXI6b3Rybw==")).toBeNull();
	});

	it("sin instrucciones guardadas no hay nada que mostrar", () => {
		expect(leerInstruccionesPago(PEDIDO)).toBeNull();
	});

	it("un almacenamiento bloqueado no rompe la compra", () => {
		// Se reemplaza el objeto entero: un `Storage` real convierte la asignación
		// de un método en una clave guardada, así que espiarlo no sirve.
		vi.stubGlobal("sessionStorage", {
			setItem: () => {
				throw new DOMException("cuota llena", "QuotaExceededError");
			},
			getItem: () => {
				throw new DOMException("bloqueado", "SecurityError");
			},
		});

		expect(guardarInstruccionesPago(PEDIDO, "datos")).toBe(false);
		expect(leerInstruccionesPago(PEDIDO)).toBeNull();
	});
});
