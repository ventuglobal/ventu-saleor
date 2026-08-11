import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getTramos } from "./tramos";

const VARIANTE = "UHJvZHVjdFZhcmlhbnQ6NDE5";
const USUARIO = "VXNlcjo1";

const TABLA = {
	visible: true,
	rut: "76.543.210-3",
	canal: "b2b-cl",
	tramos: [
		{ desde: 1, precio_unitario: 11130 },
		{ desde: 6, precio_unitario: 10020 },
	],
};

function respuesta(body: unknown, ok = true) {
	return vi.fn().mockResolvedValue({ ok, json: async () => body });
}

beforeEach(() => {
	process.env.B2B_APP_URL = "https://b2b.test";
});

afterEach(() => {
	delete process.env.B2B_APP_URL;
	vi.unstubAllGlobals();
});

describe("getTramos", () => {
	it("devuelve la tabla que entrega la App B2B", async () => {
		vi.stubGlobal("fetch", respuesta(TABLA));

		await expect(getTramos(VARIANTE, USUARIO)).resolves.toEqual(TABLA);
	});

	it("pregunta por la variante y el usuario de la sesión", async () => {
		const fetchMock = respuesta(TABLA);
		vi.stubGlobal("fetch", fetchMock);

		await getTramos(VARIANTE, USUARIO);

		const [url] = fetchMock.mock.calls[0] as [string];
		expect(url).toBe(`https://b2b.test/tramos/${VARIANTE}?user_id=${USUARIO}`);
	});

	it("propaga el motivo cuando la App B2B decide no mostrar la tabla", async () => {
		vi.stubGlobal("fetch", respuesta({ visible: false, motivo: "sin_empresa" }));

		await expect(getTramos(VARIANTE, USUARIO)).resolves.toEqual({
			visible: false,
			motivo: "sin_empresa",
		});
	});

	it("no consulta si no hay sesión", async () => {
		const fetchMock = respuesta(TABLA);
		vi.stubGlobal("fetch", fetchMock);

		const r = await getTramos(VARIANTE, null);

		expect(fetchMock).not.toHaveBeenCalled();
		expect(r).toEqual({ visible: false, motivo: "sin_identificar" });
	});

	it("sin App B2B configurada la ficha se sirve sin tabla", async () => {
		delete process.env.B2B_APP_URL;
		const fetchMock = respuesta(TABLA);
		vi.stubGlobal("fetch", fetchMock);

		await expect(getTramos(VARIANTE, USUARIO)).resolves.toEqual({
			visible: false,
			motivo: "no_disponible",
		});
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it("una App B2B caída no rompe la ficha", async () => {
		vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));

		await expect(getTramos(VARIANTE, USUARIO)).resolves.toEqual({
			visible: false,
			motivo: "no_disponible",
		});
	});

	it("un error HTTP no se pinta", async () => {
		vi.stubGlobal("fetch", respuesta({ detail: "boom" }, false));

		await expect(getTramos(VARIANTE, USUARIO)).resolves.toEqual({
			visible: false,
			motivo: "no_disponible",
		});
	});

	it("una respuesta con forma ajena se descarta", async () => {
		// Un proxy que devuelve su propio JSON no debe terminar en la ficha.
		vi.stubGlobal("fetch", respuesta({ visible: true, tramos: "muchos" }));

		await expect(getTramos(VARIANTE, USUARIO)).resolves.toEqual({
			visible: false,
			motivo: "no_disponible",
		});
	});

	it("una tabla vacía no se muestra", async () => {
		vi.stubGlobal("fetch", respuesta({ visible: true, rut: "1-9", canal: "b2b-cl", tramos: [] }));

		await expect(getTramos(VARIANTE, USUARIO)).resolves.toEqual({
			visible: false,
			motivo: "no_disponible",
		});
	});
});
