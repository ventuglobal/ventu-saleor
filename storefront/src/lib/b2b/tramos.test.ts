import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getTramos } from "./tramos";

const VARIANTE = "UHJvZHVjdFZhcmlhbnQ6NDE5";
const USUARIO = "VXNlcjo1";
const CANAL = "b2b-cl";

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
	process.env.B2B_CHANNELS = CANAL;
});

afterEach(() => {
	delete process.env.B2B_APP_URL;
	delete process.env.B2B_APP_TOKEN;
	delete process.env.B2B_CHANNELS;
	vi.unstubAllGlobals();
});

describe("getTramos", () => {
	it("devuelve la tabla que entrega la App B2B", async () => {
		vi.stubGlobal("fetch", respuesta(TABLA));

		await expect(getTramos(VARIANTE, USUARIO, CANAL)).resolves.toEqual(TABLA);
	});

	it("pregunta por la variante, el usuario de la sesión y el canal", async () => {
		const fetchMock = respuesta(TABLA);
		vi.stubGlobal("fetch", fetchMock);

		await getTramos(VARIANTE, USUARIO, CANAL);

		const [url] = fetchMock.mock.calls[0] as [string];
		expect(url).toBe(`https://b2b.test/tramos/${VARIANTE}?user_id=${USUARIO}&canal=${CANAL}`);
	});

	it("codifica el canal como cualquier otro parámetro", async () => {
		process.env.B2B_CHANNELS = `${CANAL},canal raro&x=1`;
		const fetchMock = respuesta(TABLA);
		vi.stubGlobal("fetch", fetchMock);

		await getTramos(VARIANTE, USUARIO, "canal raro&x=1");

		const [url] = fetchMock.mock.calls[0] as [string];
		expect(new URL(url).searchParams.get("canal")).toBe("canal raro&x=1");
		expect(new URL(url).searchParams.get("x")).toBeNull();
	});

	it("se autentica ante la App B2B cuando hay token", async () => {
		process.env.B2B_APP_TOKEN = "token-de-prueba";
		const fetchMock = respuesta(TABLA);
		vi.stubGlobal("fetch", fetchMock);

		await getTramos(VARIANTE, USUARIO, CANAL);

		const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(init.headers).toEqual({ Authorization: "Bearer token-de-prueba" });
	});

	it("sin token no manda cabecera de autorización", async () => {
		const fetchMock = respuesta(TABLA);
		vi.stubGlobal("fetch", fetchMock);

		await getTramos(VARIANTE, USUARIO, CANAL);

		const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(init.headers).toEqual({});
	});

	it("propaga el motivo cuando la App B2B decide no mostrar la tabla", async () => {
		vi.stubGlobal("fetch", respuesta({ visible: false, motivo: "sin_empresa" }));

		await expect(getTramos(VARIANTE, USUARIO, CANAL)).resolves.toEqual({
			visible: false,
			motivo: "sin_empresa",
		});
	});

	it("en un canal retail no consulta: ese carrito no aplica tramos", async () => {
		// Una empresa recién registrada navega retail-cl con sesión. Mostrarle
		// una tabla que su carrito después no cobra sería prometer otro precio.
		const fetchMock = respuesta(TABLA);
		vi.stubGlobal("fetch", fetchMock);

		const r = await getTramos(VARIANTE, USUARIO, "retail-cl");

		expect(fetchMock).not.toHaveBeenCalled();
		expect(r).toEqual({ visible: false, motivo: "canal_no_b2b" });
	});

	it("no consulta si no hay sesión", async () => {
		const fetchMock = respuesta(TABLA);
		vi.stubGlobal("fetch", fetchMock);

		const r = await getTramos(VARIANTE, null, CANAL);

		expect(fetchMock).not.toHaveBeenCalled();
		expect(r).toEqual({ visible: false, motivo: "sin_identificar" });
	});

	it("sin App B2B configurada la ficha se sirve sin tabla", async () => {
		delete process.env.B2B_APP_URL;
		const fetchMock = respuesta(TABLA);
		vi.stubGlobal("fetch", fetchMock);

		await expect(getTramos(VARIANTE, USUARIO, CANAL)).resolves.toEqual({
			visible: false,
			motivo: "no_disponible",
		});
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it("una App B2B caída no rompe la ficha", async () => {
		vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));

		await expect(getTramos(VARIANTE, USUARIO, CANAL)).resolves.toEqual({
			visible: false,
			motivo: "no_disponible",
		});
	});

	it("un error HTTP no se pinta", async () => {
		vi.stubGlobal("fetch", respuesta({ detail: "boom" }, false));

		await expect(getTramos(VARIANTE, USUARIO, CANAL)).resolves.toEqual({
			visible: false,
			motivo: "no_disponible",
		});
	});

	it("una respuesta con forma ajena se descarta", async () => {
		// Un proxy que devuelve su propio JSON no debe terminar en la ficha.
		vi.stubGlobal("fetch", respuesta({ visible: true, tramos: "muchos" }));

		await expect(getTramos(VARIANTE, USUARIO, CANAL)).resolves.toEqual({
			visible: false,
			motivo: "no_disponible",
		});
	});

	it("una tabla vacía no se muestra", async () => {
		vi.stubGlobal("fetch", respuesta({ visible: true, rut: "1-9", canal: "b2b-cl", tramos: [] }));

		await expect(getTramos(VARIANTE, USUARIO, CANAL)).resolves.toEqual({
			visible: false,
			motivo: "no_disponible",
		});
	});
});
