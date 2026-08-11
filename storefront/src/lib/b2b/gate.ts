import "server-only";

import { redirect } from "next/navigation";

import { getHeaderAuthState } from "@/lib/auth/get-header-user";
import { buildStorefrontPath } from "@/lib/storefront-path";
import { esCanalB2B } from "./canales";
import { getEmpresa, type Empresa } from "./company";

/**
 * Catálogo mayorista reservado a empresas registradas.
 *
 * **Esto es una puerta comercial, no un límite de seguridad.** Los canales de
 * Saleor son consultables por la API sin autenticación, así que quien conozca el
 * slug puede leer los precios del canal por su cuenta. Lo que sí queda protegido
 * es la escalera de tramos y el costo, que viven en metadata privada y no salen
 * de la App B2B.
 *
 * La distinción importa: sirve para que nadie llegue al catálogo mayorista sin
 * identificarse, no para guardar un secreto.
 */

export { esCanalB2B };

/**
 * Deja pasar solo a quien compra como empresa; si no, redirige.
 *
 * Devuelve la empresa cuando corresponde, para que quien llame pueda usarla sin
 * volver a preguntar. En un canal que no es B2B devuelve `null` y no redirige
 * nada: la tienda retail no cambia.
 */
export async function exigirEmpresa(channel: string, locale: string): Promise<Empresa | null> {
	if (!esCanalB2B(channel)) return null;

	const auth = await getHeaderAuthState();

	// `unavailable` es Saleor sin responder, no una sesión rechazada. Cerrarle la
	// puerta a un cliente ya registrado por una caída ajena sería peor que
	// dejarlo pasar: los precios del canal ya son públicos por la API.
	if (auth.status === "unavailable") return null;

	if (auth.status !== "authenticated") {
		redirect(buildStorefrontPath(locale, channel, "/login"));
	}

	const empresa = await getEmpresa(auth.user.id);
	if (!empresa.registrada) {
		// Tiene cuenta pero no empresa: le falta un paso, no el acceso.
		redirect(buildStorefrontPath(locale, channel, "/empresa"));
	}

	return empresa;
}
