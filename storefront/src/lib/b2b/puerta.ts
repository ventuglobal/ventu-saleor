import { esCanalB2B } from "./canales";

/**
 * Puerta del catálogo mayorista, resuelta en el middleware.
 *
 * Va aquí y no en cada página por dos razones. La primera es que leer la sesión
 * dentro de un componente de página obliga a renderizarla por petición: el
 * catálogo dejaría de prerenderizarse **en todos los canales**, también en
 * retail, que no tiene puerta alguna. La segunda es que el middleware corta
 * antes de renderizar, así que el contenido reservado nunca llega a emitirse;
 * una redirección desde dentro del árbol lo deja pasar en el stream y recién
 * después redirige.
 *
 * **Es una puerta comercial, no un límite de seguridad**: los canales de Saleor
 * son consultables por la API sin autenticación. Sirve para que nadie llegue al
 * catálogo mayorista sin identificarse, no para guardar un secreto. Lo que sí
 * queda protegido es la escalera de tramos y el costo, que viven en metadata
 * privada y solo salen por la App B2B.
 */

/**
 * Rutas del canal B2B que no pueden exigir sesión, porque son justamente por
 * donde se consigue. `empresa` completa el alta de quien ya entró.
 */
const ABIERTAS = new Set(["login", "signup", "empresa", "reset-password", "set-password"]);

export function requiereSesion(channel: string, resto: string[]): boolean {
	if (!esCanalB2B(channel)) return false;
	const primero = resto[0] ?? "";
	return !ABIERTAS.has(primero);
}

/**
 * Nombres de las cookies del SDK de autenticación de Saleor. Se replican aquí
 * porque el middleware no puede importar el módulo del servidor que las arma.
 */
export function nombresDeCookieDeSesion(saleorApiUrl: string): [string, string] {
	return [`${saleorApiUrl}+saleor_auth_access_token`, `${saleorApiUrl}+saleor_auth_module_refresh_token`];
}
