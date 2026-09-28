import { Suspense } from "react";
import { connection } from "next/server";
import { getTranslations } from "next-intl/server";
import { esCanalB2B } from "@/lib/b2b/canales";
import { AuthFormSection } from "@/ui/components/auth/auth-form-section";
import { SignUpForm } from "@/ui/components/sign-up-form";

type SignUpPageProps = { params: Promise<{ locale: string; channel: string }> };

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }) {
	const { locale } = await params;
	const t = await getTranslations({ locale, namespace: "account.metadata" });
	return {
		title: t("signupTitle"),
		description: t("signupDescription"),
	};
}

export default function SignUpPage(props: SignUpPageProps) {
	return (
		<Suspense fallback={<SignUpSkeleton />}>
			<SignUpEntry {...props} />
		</Suspense>
	);
}

/**
 * Si el canal es de empresa se decide con `B2B_CHANNELS` en cada petición, no
 * al compilar: la imagen se construye sin esa variable, y leerla durante el
 * prerenderizado dejaría horneado el formulario retail también en los canales
 * de empresa. `connection()` lleva el render a la petición; por eso va dentro
 * del `Suspense`.
 */
async function SignUpEntry({ params }: SignUpPageProps) {
	const { channel } = await params;
	await connection();

	return (
		<AuthFormSection>
			<SignUpForm empresaRequerida={esCanalB2B(channel)} />
		</AuthFormSection>
	);
}

function SignUpSkeleton() {
	return (
		<AuthFormSection>
			<div className="mx-auto my-16 w-full max-w-md">
				<div className="rounded-lg border border-border bg-card p-8 shadow-sm">
					<div className="mb-6 flex flex-col items-center gap-2">
						<div className="h-7 w-44 animate-pulse rounded bg-secondary" />
						<div className="h-4 w-52 animate-pulse rounded bg-secondary" />
					</div>
					<div className="space-y-4">
						<div className="grid grid-cols-2 gap-4">
							<div className="space-y-1.5">
								<div className="h-4 w-20 animate-pulse rounded bg-secondary" />
								<div className="h-12 w-full animate-pulse rounded-md bg-secondary" />
							</div>
							<div className="space-y-1.5">
								<div className="h-4 w-20 animate-pulse rounded bg-secondary" />
								<div className="h-12 w-full animate-pulse rounded-md bg-secondary" />
							</div>
						</div>
						<div className="space-y-1.5">
							<div className="h-4 w-24 animate-pulse rounded bg-secondary" />
							<div className="h-12 w-full animate-pulse rounded-md bg-secondary" />
						</div>
						<div className="space-y-1.5">
							<div className="h-4 w-16 animate-pulse rounded bg-secondary" />
							<div className="h-12 w-full animate-pulse rounded-md bg-secondary" />
						</div>
						<div className="space-y-1.5">
							<div className="h-4 w-32 animate-pulse rounded bg-secondary" />
							<div className="h-12 w-full animate-pulse rounded-md bg-secondary" />
						</div>
						<div className="bg-foreground/10 h-12 w-full animate-pulse rounded-md" />
					</div>
				</div>
			</div>
		</AuthFormSection>
	);
}
