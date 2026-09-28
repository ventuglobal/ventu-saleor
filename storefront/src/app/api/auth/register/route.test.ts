import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { NextRequest } from "next/server";

/**
 * RUT y razón social en el registro: obligatorios solo en canales de empresa.
 * Saleor y la App B2B van simulados; la prueba no sale a la red.
 *
 * `accountRegister` de Saleor 3.23 devuelve el id vacío, así que en un canal de
 * empresa la ruta pide el id real con `tokenCreate` antes de dar de alta la
 * empresa.
 */

const CORREO = "compras@ejemplo.cl";
const CLAVE = "clave-segura-1";
/** Lo que devolvería `accountRegister` en Saleor 3.23: id vacío. */
const USUARIO_REGISTRO = { id: "", email: CORREO };
/** El id real, que solo llega por `tokenCreate`. */
const ID_REAL = "VXNlcjo1";
/** Si la ruta pidiera el token, nunca debe salir de ella. */
const TOKEN = "eyJ-token-que-nunca-debe-salir";

const executeRawGraphQL = vi.fn();
const registrarEmpresa = vi.fn();

vi.mock("@/lib/auth/auth-rate-limit", () => ({
	rejectIfRateLimited: () => null,
}));

vi.mock("@/lib/graphql", () => ({
	executeRawGraphQL: (...args: unknown[]) => executeRawGraphQL(...args),
}));

vi.mock("@/lib/b2b/company", () => ({
	registrarEmpresa: (...args: unknown[]) => registrarEmpresa(...args),
}));

import { EMPRESA_PENDIENTE_REGISTRO, MENSAJE_RUT_INVALIDO } from "@/lib/b2b/errores";

import { POST } from "./route";

type Opciones = { query: string; variables: Record<string, unknown> };

/** Las llamadas a Saleor de un nombre de operación, en orden. */
function llamadas(operacion: "AccountRegister" | "TokenCreateRegistro"): Opciones[] {
	return executeRawGraphQL.mock.calls
		.map(([opciones]) => opciones as Opciones)
		.filter((o) => o.query.includes(`mutation ${operacion}`));
}

type Respuestas = {
	register?: unknown;
	tokenCreate?: unknown;
};

/** Simula Saleor respondiendo según la mutación, no según el orden de llamada. */
function saleor({ register, tokenCreate }: Respuestas = {}) {
	executeRawGraphQL.mockImplementation(async ({ query }: Opciones) => {
		if (query.includes("mutation AccountRegister")) {
			return register ?? { ok: true, data: { accountRegister: { user: USUARIO_REGISTRO, errors: [] } } };
		}
		if (query.includes("mutation TokenCreateRegistro")) {
			return (
				tokenCreate ?? {
					ok: true,
					// Saleor también trae el token si se pidiera; la ruta no lo pide y,
					// aunque llegara, no debe reenviarlo.
					data: { tokenCreate: { token: TOKEN, user: { id: ID_REAL }, errors: [] } },
				}
			);
		}
		throw new Error(`consulta inesperada: ${query}`);
	});
}

function registrar(cuerpo: Record<string, unknown>) {
	return POST(
		new NextRequest("http://localhost/api/auth/register", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ email: CORREO, password: CLAVE, ...cuerpo }),
		}),
	);
}

const EMPRESA = { channel: "b2b-cl", rut: " 76.543.210-3 ", razonSocial: "Santa Teresa" };

let consola: MockInstance[];

/** Todo lo que la ruta escribió en la consola, como texto. */
function registrado(): string {
	return JSON.stringify(consola.flatMap((espia) => espia.mock.calls));
}

beforeEach(() => {
	process.env.B2B_CHANNELS = "b2b-cl";
	saleor();
	registrarEmpresa.mockResolvedValue({ ok: true, rut: "76543210-3" });
	consola = (["log", "info", "warn", "error", "debug"] as const).map((nivel) =>
		vi.spyOn(console, nivel).mockImplementation(() => {}),
	);
});

afterEach(() => {
	// Ninguna prueba debe dejar en el log el correo, la contraseña ni el token.
	const log = registrado();
	expect(log).not.toContain(CORREO);
	expect(log).not.toContain(CLAVE);
	expect(log).not.toContain(TOKEN);

	delete process.env.B2B_CHANNELS;
	executeRawGraphQL.mockReset();
	registrarEmpresa.mockReset();
	vi.restoreAllMocks();
});

describe("POST /api/auth/register", () => {
	it("en un canal de empresa rechaza el registro sin RUT antes de crear la cuenta", async () => {
		const res = await registrar({ channel: "b2b-cl", razonSocial: "Santa Teresa" });

		expect(res.status).toBe(400);
		const dato = (await res.json()) as { errors: Array<{ code: string }> };
		expect(dato.errors[0].code).toBe("EMPRESA_REQUERIDA");
		expect(executeRawGraphQL).not.toHaveBeenCalled();
		expect(registrarEmpresa).not.toHaveBeenCalled();
	});

	it("en un canal de empresa rechaza el registro sin razón social", async () => {
		const res = await registrar({ channel: "b2b-cl", rut: "76.543.210-3" });

		expect(res.status).toBe(400);
		expect(executeRawGraphQL).not.toHaveBeenCalled();
	});

	it("en un canal de empresa pide el id con tokenCreate y registra la empresa con ese id", async () => {
		const res = await registrar(EMPRESA);

		expect(res.status).toBe(200);
		const dato = (await res.json()) as Record<string, unknown>;
		expect(dato.empresa).toEqual({ ok: true });

		// Primero la cuenta, después el id, después la empresa.
		const [register, tokenCreate] = executeRawGraphQL.mock.calls.map(([o]) => (o as Opciones).query);
		expect(register).toContain("mutation AccountRegister");
		expect(tokenCreate).toContain("mutation TokenCreateRegistro");
		expect(llamadas("TokenCreateRegistro")[0].variables).toEqual({ email: CORREO, password: CLAVE });

		expect(registrarEmpresa).toHaveBeenCalledOnce();
		expect(registrarEmpresa).toHaveBeenCalledWith(
			ID_REAL,
			expect.objectContaining({ rut: "76.543.210-3", razonSocial: "Santa Teresa" }),
		);
	});

	it("tokenCreate no pide ningún token, y ninguno sale en la respuesta", async () => {
		const res = await registrar(EMPRESA);

		const query = llamadas("TokenCreateRegistro")[0].query;
		expect(query).not.toMatch(/\btoken\b|refreshToken|csrfToken/);

		const texto = await res.text();
		expect(texto).not.toContain(TOKEN);
		expect(texto).not.toContain(CLAVE);
		// El registro no inicia sesión: no hay cookies de autenticación.
		expect(res.headers.get("set-cookie")).toBeNull();
	});

	it("si Saleor pide confirmar el correo, la cuenta queda creada y la empresa pendiente", async () => {
		saleor({
			tokenCreate: {
				ok: true,
				data: { tokenCreate: { user: null, errors: [{ field: "email", code: "ACCOUNT_NOT_CONFIRMED" }] } },
			},
		});

		const res = await registrar(EMPRESA);

		expect(res.status).toBe(200);
		const dato = (await res.json()) as { empresa?: unknown };
		expect(dato.empresa).toEqual({ ok: false, pendiente: true, mensaje: EMPRESA_PENDIENTE_REGISTRO });
		expect(registrarEmpresa).not.toHaveBeenCalled();
		expect(registrado()).toContain("ACCOUNT_NOT_CONFIRMED");
	});

	it("unas credenciales rechazadas dan el mismo pendiente que una cuenta sin confirmar", async () => {
		saleor({
			tokenCreate: {
				ok: true,
				data: { tokenCreate: { user: null, errors: [{ field: "email", code: "INVALID_CREDENTIALS" }] } },
			},
		});

		const res = await registrar(EMPRESA);

		await expect(res.json()).resolves.toMatchObject({
			empresa: { ok: false, pendiente: true, mensaje: EMPRESA_PENDIENTE_REGISTRO },
		});
		expect(registrarEmpresa).not.toHaveBeenCalled();
	});

	it("si tokenCreate no llega a Saleor, la empresa queda pendiente", async () => {
		saleor({
			tokenCreate: {
				ok: false,
				error: { type: "network", message: "TokenCreateRegistro: Failed to execute", isRetryable: true },
			},
		});

		const res = await registrar(EMPRESA);

		expect(res.status).toBe(200);
		await expect(res.json()).resolves.toMatchObject({ empresa: { ok: false, pendiente: true } });
		expect(registrarEmpresa).not.toHaveBeenCalled();
	});

	it("si la App B2B rechaza el alta, la cuenta queda creada y el motivo llega traducido", async () => {
		registrarEmpresa.mockResolvedValue({
			ok: false,
			status: 422,
			mensaje: MENSAJE_RUT_INVALIDO,
			code: "RUT_INVALIDO",
		});

		const res = await registrar(EMPRESA);

		expect(res.status).toBe(200);
		const { empresa } = (await res.json()) as {
			empresa: { ok: boolean; pendiente: boolean; mensaje: string };
		};
		expect(empresa).toMatchObject({ ok: false, pendiente: true, code: "RUT_INVALIDO" });
		expect(empresa.mensaje).toContain(MENSAJE_RUT_INVALIDO);
		expect(empresa.mensaje).toContain("Registrar empresa");
	});

	it("en retail no exige RUT ni llama a tokenCreate", async () => {
		const res = await registrar({ channel: "retail-cl" });

		expect(res.status).toBe(200);
		expect(executeRawGraphQL).toHaveBeenCalledOnce();
		expect(llamadas("TokenCreateRegistro")).toHaveLength(0);
		expect(registrarEmpresa).not.toHaveBeenCalled();
	});

	it("en retail ignora un RUT aunque venga", async () => {
		const res = await registrar({ channel: "retail-cl", rut: "76.543.210-3", razonSocial: "Santa Teresa" });

		expect(res.status).toBe(200);
		const dato = (await res.json()) as { empresa?: unknown };
		expect(dato.empresa).toBeUndefined();
		expect(llamadas("TokenCreateRegistro")).toHaveLength(0);
		expect(registrarEmpresa).not.toHaveBeenCalled();
	});

	it("los errores de validación de Saleor llegan con su código y un mensaje en castellano", async () => {
		saleor({
			register: {
				ok: true,
				data: {
					accountRegister: {
						user: null,
						errors: [
							{ field: "password", message: "This password is too common.", code: "PASSWORD_TOO_COMMON" },
						],
					},
				},
			},
		});

		const res = await registrar(EMPRESA);

		expect(res.status).toBe(400);
		const { errors } = (await res.json()) as {
			errors: Array<{ field: string; code: string; message: string }>;
		};
		expect(errors[0]).toMatchObject({ field: "password", code: "PASSWORD_TOO_COMMON" });
		expect(errors[0].message).toMatch(/contraseña/);
		expect(errors[0].message).not.toContain("too common");
		expect(llamadas("TokenCreateRegistro")).toHaveLength(0);
		expect(registrarEmpresa).not.toHaveBeenCalled();
	});

	it("si Saleor no responde al registro, responde 503 sin el error crudo", async () => {
		saleor({
			register: {
				ok: false,
				error: { type: "network", message: "AccountRegister: Failed to execute", isRetryable: true },
			},
		});

		const res = await registrar(EMPRESA);

		expect(res.status).toBe(503);
		const texto = await res.text();
		expect(texto).not.toContain("Failed to execute");
		expect(llamadas("TokenCreateRegistro")).toHaveLength(0);
	});
});
