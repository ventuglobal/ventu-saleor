import { Building2, Clock } from "lucide-react";
import { cookies } from "next/headers";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { getHeaderAuthState } from "@/lib/auth/get-header-user";
import { avisoDeEmpresa } from "@/lib/b2b/aviso-empresa";
import { esCanalB2B } from "@/lib/b2b/canales";
import { getEmpresaPorPeticion } from "@/lib/b2b/company";
import { buildStorefrontPath } from "@/lib/storefront-path";

import { OcultoEnEmpresa } from "./oculto-en-empresa";

/**
 * Aviso de empresa para quien tiene sesión en un canal B2B: sin empresa —el alta
 * falló al registrarse, o la cuenta viene de retail— no puede hacer pedidos, y
 * sin este aviso recién lo descubriría en el pago.
 *
 * Tiene que salir barato porque va en todas las páginas del canal:
 * - retail corta antes de leer cookies, así sus páginas siguen prerenderizándose
 *   y no consultan nada;
 * - sin sesión no se consulta la App B2B;
 * - la sesión y la empresa salen de funciones con `cache`, las mismas que usa el
 *   menú de la cuenta: una sola consulta de cada una por petición.
 */
export async function AvisoEmpresa({ locale, channel }: { locale: string; channel: string }) {
	if (!esCanalB2B(channel)) return null;

	// Por petición bajo PPR: el aviso depende de quién mira.
	await cookies();

	const auth = await getHeaderAuthState();
	if (auth.status !== "authenticated") return null;

	const aviso = avisoDeEmpresa(await getEmpresaPorPeticion(auth.user.id));
	if (!aviso) return null;

	const t = await getTranslations({ locale, namespace: "account" });
	const Icono = aviso === "sin_empresa" ? Building2 : Clock;

	return (
		<OcultoEnEmpresa>
			<div className="border-b border-border bg-muted" data-aviso-empresa={aviso}>
				<div className="container-content flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm text-foreground">
					<Icono className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
					<p>{aviso === "sin_empresa" ? t("empresaAviso.sinEmpresa") : t("empresaAviso.enRevision")}</p>
					{aviso === "sin_empresa" ? (
						<Link
							href={buildStorefrontPath(locale, channel, "/empresa")}
							className="font-medium underline underline-offset-2 hover:no-underline"
						>
							{t("empresaAviso.sinEmpresaCta")}
						</Link>
					) : null}
				</div>
			</div>
		</OcultoEnEmpresa>
	);
}
