import { cookies } from "next/headers";

import { getHeaderAuthState } from "@/lib/auth/get-header-user";
import { esCanalB2B } from "@/lib/b2b/canales";
import { getEmpresaPorPeticion } from "@/lib/b2b/company";

import { UserMenu } from "./user-menu";
import { UserMenuLoginLink } from "./user-menu-login-link";
import { UserMenuUnavailable } from "./user-menu-unavailable";

export async function UserMenuServer({ locale, channel }: { locale: string; channel: string }) {
	// Request-dynamic under PPR — never serve a prerendered anonymous menu when cookies exist.
	await cookies();

	const auth = await getHeaderAuthState();

	switch (auth.status) {
		case "authenticated": {
			// En un canal de empresa, quien tiene cuenta pero no empresa —el alta
			// falló al registrarse, o la cuenta viene de retail— necesita un camino a
			// /empresa: sin ella no puede hacer pedidos por pagar. Se pregunta solo en
			// esos canales para no sumar una llamada a la App B2B en cada página retail,
			// y con la misma consulta por petición que el aviso de empresa. Si la App
			// B2B no contestó no se ofrece: quizá ya la registró.
			let registrarEmpresa = false;
			if (esCanalB2B(channel)) {
				const empresa = await getEmpresaPorPeticion(auth.user.id);
				registrarEmpresa = !empresa.registrada && !empresa.error;
			}
			return <UserMenu user={auth.user} registrarEmpresa={registrarEmpresa} />;
		}
		case "unavailable":
			return <UserMenuUnavailable />;
		case "guest":
			return <UserMenuLoginLink locale={locale} channel={channel} />;
	}
}
