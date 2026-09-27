import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

/**
 * La empresa de la sesión y su alta. La sesión y la App B2B van simuladas: la
 * prueba no sale a la red.
 */

const USUARIO = "VXNlcjo1";

const getHeaderAuthState = vi.fn();
const getEmpresa = vi.fn();
const registrarEmpresa = vi.fn();

vi.mock("@/lib/auth/get-header-user", () => ({
	getHeaderAuthState: () => getHeaderAuthState(),
}));

vi.mock("@/lib/auth/auth-rate-limit", () => ({
	rejectIfRateLimited: () => null,
}));

vi.mock("@/lib/b2b/company", () => ({
	getEmpresa: (id: string) => getEmpresa(id),
	registrarEmpresa: (id: string, datos: unknown) => registrarEmpresa(id, datos),
}));

import { MENSAJE_EMPRESA_NO_DISPONIBLE, MENSAJE_RUT_INVALIDO } from "@/lib/b2b/errores";

import { GET, POST } from "./route";

function alta(cuerpo: unknown) {
	return POST(
		new NextRequest("http://localhost/api/b2b/company", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(cuerpo),
		}),
	);
}

beforeEach(() => {
	getHeaderAuthState.mockResolvedValue({ status: "authenticated", user: { id: USUARIO } });
});

afterEach(() => {
	getHeaderAuthState.mockReset();
	getEmpresa.mockReset();
	registrarEmpresa.mockReset();
});

describe("GET /api/b2b/company", () => {
	it("sin sesión responde sin empresa y no autenticado, sin llamar a la App B2B", async () => {
		getHeaderAuthState.mockResolvedValue({ status: "guest" });

		const res = await GET();

		await expect(res.json()).resolves.toEqual({ registrada: false, autenticado: false });
		expect(getEmpresa).not.toHaveBeenCalled();
	});

	it("con sesión y sin empresa lo dice, marcando que hay sesión", async () => {
		getEmpresa.mockResolvedValue({ registrada: false });

		const res = await GET();

		await expect(res.json()).resolves.toEqual({ registrada: false, autenticado: true });
		expect(getEmpresa).toHaveBeenCalledWith(USUARIO);
	});

	it("si la App B2B no contesta responde 503, no «sin empresa»", async () => {
		getEmpresa.mockResolvedValue({ registrada: false, error: true });

		const res = await GET();

		expect(res.status).toBe(503);
		await expect(res.json()).resolves.toEqual({ mensaje: MENSAJE_EMPRESA_NO_DISPONIBLE });
	});

	it("si no se puede resolver la sesión responde 503", async () => {
		getHeaderAuthState.mockResolvedValue({ status: "unavailable" });

		const res = await GET();

		expect(res.status).toBe(503);
		expect(getEmpresa).not.toHaveBeenCalled();
	});

	it("entrega la empresa con su aprobación", async () => {
		getEmpresa.mockResolvedValue({ registrada: true, aprobada: false, estado: "pendiente", medios_pago: [] });

		const res = await GET();

		await expect(res.json()).resolves.toMatchObject({ registrada: true, aprobada: false, autenticado: true });
	});
});

describe("POST /api/b2b/company", () => {
	it("un rechazo llega con el mensaje traducido y su código", async () => {
		registrarEmpresa.mockResolvedValue({
			ok: false,
			status: 422,
			mensaje: MENSAJE_RUT_INVALIDO,
			code: "RUT_INVALIDO",
		});

		const res = await alta({ rut: "76.543.210-4", razonSocial: "Santa Teresa SpA" });

		expect(res.status).toBe(422);
		await expect(res.json()).resolves.toEqual({ mensaje: MENSAJE_RUT_INVALIDO, code: "RUT_INVALIDO" });
		expect(registrarEmpresa).toHaveBeenCalledWith(USUARIO, expect.objectContaining({ rut: "76.543.210-4" }));
	});

	it("sin sesión no da de alta", async () => {
		getHeaderAuthState.mockResolvedValue({ status: "guest" });

		const res = await alta({ rut: "76.543.210-3", razonSocial: "Santa Teresa SpA" });

		expect(res.status).toBe(401);
		expect(registrarEmpresa).not.toHaveBeenCalled();
	});
});
