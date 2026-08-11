import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { getHeaderAuthState } from "@/lib/auth/get-header-user";
import { getEmpresa } from "@/lib/b2b/company";
import { buildStorefrontPath } from "@/lib/storefront-path";
import { AuthFormSection } from "@/ui/components/auth/auth-form-section";
import { EmpresaForm } from "@/ui/components/empresa-form";

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }) {
	const { locale } = await params;
	const t = await getTranslations({ locale, namespace: "account" });
	return { title: t("empresa.title"), description: t("empresa.subtitle") };
}

/**
 * Alta de empresa para una cuenta ya creada.
 *
 * No lleva la puerta del catálogo (`exigirEmpresa`) porque es precisamente su
 * destino: exigir empresa aquí sería un ciclo de redirecciones.
 */
export default async function EmpresaPage(props: { params: Promise<{ locale: string; channel: string }> }) {
	const { locale, channel } = await props.params;

	const auth = await getHeaderAuthState();
	if (auth.status !== "authenticated") {
		redirect(buildStorefrontPath(locale, channel, "/login"));
	}

	// Ya tiene empresa: no hay nada que completar y volver a pedir el RUT
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
