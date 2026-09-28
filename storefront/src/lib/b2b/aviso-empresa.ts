import type { ResultadoEmpresa } from "./company";

export type AvisoEmpresa = "sin_empresa" | "en_revision";

/**
 * Qué aviso de empresa ve una cuenta con sesión en un canal B2B.
 *
 * Sin respuesta de la App B2B no se avisa nada: pedirle «registra tu empresa» a
 * quien quizá ya la registró lo mandaría a un alta que termina en «ya tiene una
 * empresa». Una empresa aprobada no necesita aviso.
 */
export function avisoDeEmpresa(empresa: ResultadoEmpresa): AvisoEmpresa | null {
	if (!empresa.registrada) return empresa.error ? null : "sin_empresa";
	return empresa.aprobada ? null : "en_revision";
}
