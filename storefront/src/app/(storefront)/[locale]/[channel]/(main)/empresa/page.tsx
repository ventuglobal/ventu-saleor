import { Suspense } from "react";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { getHeaderAuthState } from "@/lib/auth/get-header-user";
import { getEmpresa } from "@/lib/b2b/company";
import { buildStorefrontPath } from "@/lib/storefront-path";
import { AuthFormSection } from "@/ui/components/auth/auth-form-section";
import { EmpresaForm } from "@/ui/components/empresa-form";

type EmpresaPageProps = { params: Promise<{ locale: string; channel: string }> };

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }) {
	const { locale } = await params;
	const t = await getTranslations({ locale, namespace: "account" });
	return { title: t("empresa.title"), description: t("empresa.subtitle") };
}

/**
 * Alta de empresa para una cuenta ya creada.
 *
 * La sesión se lee dentro de un `Suspense`, como el resto de las páginas de
 * cuenta: leerla en el cuerpo de la página haría fallar el prerenderizado.
 *
 * No lleva la puerta del catálogo porque es precisamente su destino: exigir
 * empresa aquí sería un ciclo de redirecciones.
 */
export default function EmpresaPage(props: EmpresaPageProps) {
	return (
		<Suspense fallback={null}>
			<EmpresaEntry {...props} />
		</Suspense>
	);
}

async function EmpresaEntry({ params }: EmpresaPageProps) {
	const { locale, channel } = await params;

	const auth = await getHeaderAuthState();
	if (auth.status !== "authenticated") {
		redirect(buildStorefrontPath(locale, channel, "/login"));
	}

	// Ya tiene empresa: no hay nada que completar, y volver a pedir el RUT
	// invitaría a intentar cambiarlo.
	const empresa = await getEmpresa(auth.user.id);
	if (empresa.registrada) {
		redirect(buildStorefrontPath(locale, channel, "/products"));
	}

	return (
		<AuthFormSection>
			<EmpresaForm />
		</AuthFormSection>
	);
}
