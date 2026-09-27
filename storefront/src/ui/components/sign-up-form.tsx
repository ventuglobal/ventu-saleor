"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Mail, Lock, Eye, EyeOff, User, Building2, Hash } from "lucide-react";
import { Button } from "@/ui/components/ui/button";
import { Input } from "@/ui/components/ui/input";
import { Label } from "@/ui/components/ui/label";
import { buildAccountConfirmationRedirectUrl } from "@/lib/auth/account-confirmation-url";
import { empresaDelRegistro } from "@/lib/b2b/registro";
import { buildStorefrontPath } from "@/lib/storefront-path";
import { cn } from "@/lib/utils";

/** Lo que responde la ruta de registro sobre la empresa, solo en canales de empresa. */
type EmpresaRegistro = { ok: true } | { ok: false; pendiente?: boolean; mensaje?: string; code?: string };

/**
 * Error de la ruta de registro → texto del formulario. Se traduce por código
 * con los textos de cada idioma; el `message` de la respuesta es solo para
 * otros clientes.
 */
function claveDeError(code?: string) {
	switch (code) {
		case "UNIQUE":
			return "errors.accountExists" as const;
		case "EMPRESA_REQUERIDA":
			return "errors.empresaRequerida" as const;
		case "RUT_INVALIDO":
			return "errors.rutInvalido" as const;
		case "PASSWORD_TOO_SHORT":
		case "PASSWORD_TOO_COMMON":
		case "PASSWORD_ENTIRELY_NUMERIC":
		case "PASSWORD_TOO_SIMILAR":
		case "INVALID_PASSWORD":
			return "errors.passwordWeak" as const;
		case "NETWORK":
			return "errors.serviceUnavailable" as const;
		case "RATE_LIMITED":
			return "errors.tooManyAttempts" as const;
		default:
			return "errors.createAccountFailed" as const;
	}
}

type SignUpFormProps = {
	/**
	 * El canal es de empresa: se piden RUT y razón social. Lo calcula el
	 * servidor —`B2B_CHANNELS` no existe en el navegador— y en retail el
	 * formulario queda como el de cualquier tienda.
	 */
	empresaRequerida?: boolean;
};

export function SignUpForm({ empresaRequerida = false }: SignUpFormProps) {
	const t = useTranslations("account");
	const params = useParams<{ locale: string; channel: string }>();

	const [rut, setRut] = useState("");
	const [razonSocial, setRazonSocial] = useState("");
	const [firstName, setFirstName] = useState("");
	const [lastName, setLastName] = useState("");
	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [confirmPassword, setConfirmPassword] = useState("");
	const [showPassword, setShowPassword] = useState(false);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [error, setError] = useState("");
	const [success, setSuccess] = useState(false);
	/** Qué pasó con la empresa: se muestra en la pantalla de éxito, no como error. */
	const [empresa, setEmpresa] = useState<EmpresaRegistro | null>(null);

	const validateEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setError("");

		if (!email || !validateEmail(email)) {
			setError(t("errors.invalidEmail"));
			return;
		}

		if (password.length < 8) {
			setError(t("errors.passwordMinLength"));
			return;
		}

		if (password !== confirmPassword) {
			setError(t("errors.passwordsMismatch"));
			return;
		}

		const datosEmpresa = empresaDelRegistro(empresaRequerida, rut, razonSocial);
		if (!datosEmpresa.ok) {
			setError(t("errors.empresaRequerida"));
			return;
		}

		setIsSubmitting(true);

		try {
			const response = await fetch("/api/auth/register", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					email,
					password,
					firstName,
					lastName,
					// En retail no viaja nada de empresa: el servidor lo ignoraría
					// igual, pero no hay por qué mandar datos que nadie pidió.
					...(datosEmpresa.empresa ?? {}),
					channel: params.channel,
					redirectUrl: buildAccountConfirmationRedirectUrl(
						window.location.origin,
						params.locale,
						params.channel,
					),
				}),
			});

			const data = (await response.json()) as {
				errors?: Array<{ message: string; code?: string | null }>;
				empresa?: EmpresaRegistro;
			};

			if (data.errors?.length) {
				setError(t(claveDeError(data.errors[0].code ?? undefined)));
				return;
			}

			// La cuenta quedó creada aunque el alta de empresa no: eso es un éxito
			// con un paso pendiente, no un error. Mostrarlo en rojo haría pensar que
			// hay que registrarse de nuevo, y el correo ya está tomado.
			setEmpresa(data.empresa ?? null);
			setSuccess(true);
		} catch {
			setError(t("errors.generic"));
		} finally {
			setIsSubmitting(false);
		}
	};

	if (success) {
		return (
			<div className="mx-auto mt-16 w-full max-w-md">
				<div className="rounded-lg border border-border bg-card p-8 shadow-sm">
					<div className="text-center">
						<div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
							<svg
								aria-hidden="true"
								className="h-6 w-6 text-green-600"
								fill="none"
								viewBox="0 0 24 24"
								stroke="currentColor"
							>
								<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
							</svg>
						</div>
						<h2 className="text-xl font-semibold">{t("signup.successTitle")}</h2>
						<p className="mt-2 text-muted-foreground">{t("signup.successBody")}</p>
						{empresa?.ok ? (
							<p className="mt-4 rounded-md bg-muted p-3 text-sm text-foreground" role="status">
								{t("signup.empresaEnRevision")}
							</p>
						) : empresa ? (
							// El motivo viene de la ruta, ya en castellano y sin el error
							// crudo; si no viene, el texto genérico dice qué hacer.
							<div className="mt-4 rounded-md bg-muted p-3 text-sm text-foreground" role="status">
								<p>{empresa.mensaje || t("signup.empresaPendiente")}</p>
								<Link
									href={buildStorefrontPath(params.locale, params.channel, "/empresa")}
									className="mt-2 inline-block font-medium underline underline-offset-2 hover:no-underline"
								>
									{t("signup.completeCompany")}
								</Link>
							</div>
						) : null}
						<Link
							href={buildStorefrontPath(params.locale, params.channel, "/login")}
							className="mt-6 inline-block text-sm font-medium text-foreground underline underline-offset-2 hover:no-underline"
						>
							{t("signup.goToSignIn")}
						</Link>
					</div>
				</div>
			</div>
		);
	}

	return (
		<div className="mx-auto mt-16 w-full max-w-md">
			<div className="rounded-lg border border-border bg-card p-8 shadow-sm">
				<div className="mb-6 text-center">
					<h1 className="text-balance text-h1">{t("signup.title")}</h1>
					<p className="mt-2 text-sm text-muted-foreground">
						{t("signup.hasAccount")}{" "}
						<Link
							href={buildStorefrontPath(params.locale, params.channel, "/login")}
							className="font-medium text-foreground underline underline-offset-2 hover:no-underline"
						>
							{t("signup.signIn")}
						</Link>
					</p>
				</div>

				<form onSubmit={handleSubmit} className="space-y-4">
					{error && (
						<div role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
							{error}
						</div>
					)}

					{empresaRequerida && (
						<>
							<div className="space-y-1.5">
								<Label htmlFor="razonSocial" className="text-sm font-medium">
									{t("fields.razonSocial")}
								</Label>
								<div className="relative">
									<Building2 className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
									<Input
										id="razonSocial"
										type="text"
										placeholder={t("placeholders.razonSocial")}
										autoComplete="organization"
										value={razonSocial}
										onChange={(e) => setRazonSocial(e.target.value)}
										className="h-12 pl-10"
										required
									/>
								</div>
							</div>

							<div className="space-y-1.5">
								<Label htmlFor="rut" className="text-sm font-medium">
									{t("fields.rut")}
								</Label>
								<div className="relative">
									<Hash className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
									<Input
										id="rut"
										type="text"
										placeholder={t("placeholders.rut")}
										inputMode="text"
										spellCheck={false}
										value={rut}
										onChange={(e) => setRut(e.target.value)}
										className="h-12 pl-10"
										required
									/>
								</div>
								<p className="text-xs text-muted-foreground">{t("signup.rutHint")}</p>
							</div>
						</>
					)}

					<div className="grid grid-cols-2 gap-4">
						<div className="space-y-1.5">
							<Label htmlFor="firstName" className="text-sm font-medium">
								{t("fields.firstName")}
							</Label>
							<div className="relative">
								<User className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
								<Input
									id="firstName"
									type="text"
									placeholder={t("placeholders.firstName")}
									autoComplete="given-name"
									value={firstName}
									onChange={(e) => setFirstName(e.target.value)}
									className="h-12 pl-10"
								/>
							</div>
						</div>
						<div className="space-y-1.5">
							<Label htmlFor="lastName" className="text-sm font-medium">
								{t("fields.lastName")}
							</Label>
							<Input
								id="lastName"
								type="text"
								placeholder={t("placeholders.lastName")}
								autoComplete="family-name"
								value={lastName}
								onChange={(e) => setLastName(e.target.value)}
								className="h-12"
							/>
						</div>
					</div>

					<div className="space-y-1.5">
						<Label htmlFor="email" className="text-sm font-medium">
							{t("fields.emailAddress")}
						</Label>
						<div className="relative">
							<Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
							<Input
								id="email"
								type="email"
								placeholder={t("placeholders.email")}
								autoComplete="email"
								spellCheck={false}
								value={email}
								onChange={(e) => setEmail(e.target.value)}
								className="h-12 pl-10"
								required
							/>
						</div>
					</div>

					<div className="space-y-1.5">
						<Label htmlFor="password" className="text-sm font-medium">
							{t("fields.password")}
						</Label>
						<div className="relative">
							<Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
							<Input
								id="password"
								type={showPassword ? "text" : "password"}
								placeholder={t("placeholders.newPasswordMin")}
								autoComplete="new-password"
								value={password}
								onChange={(e) => setPassword(e.target.value)}
								className="h-12 pl-10 pr-10"
								required
								minLength={8}
							/>
							<button
								type="button"
								onClick={() => setShowPassword(!showPassword)}
								aria-label={showPassword ? t("common.hidePassword") : t("common.showPassword")}
								className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
							>
								{showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
							</button>
						</div>
					</div>

					<div className="space-y-1.5">
						<Label htmlFor="confirmPassword" className="text-sm font-medium">
							{t("fields.confirmPassword")}
						</Label>
						<div className="relative">
							<Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
							<Input
								id="confirmPassword"
								type={showPassword ? "text" : "password"}
								placeholder={t("placeholders.reenterPassword")}
								autoComplete="new-password"
								value={confirmPassword}
								onChange={(e) => setConfirmPassword(e.target.value)}
								className={cn(
									"h-12 pl-10",
									confirmPassword && password !== confirmPassword && "border-destructive",
								)}
								required
							/>
						</div>
						{confirmPassword && password !== confirmPassword && (
							<p className="text-sm text-destructive">{t("errors.passwordsMismatch")}</p>
						)}
					</div>

					<Button type="submit" disabled={isSubmitting} className="h-12 w-full text-base font-semibold">
						{isSubmitting ? t("signup.submitting") : t("signup.submit")}
					</Button>

					<p className="text-center text-xs text-muted-foreground">
						{t.rich("signup.terms", {
							terms: (chunks) => (
								<Link href="#" className="underline hover:no-underline">
									{chunks}
								</Link>
							),
							privacy: (chunks) => (
								<Link href="#" className="underline hover:no-underline">
									{chunks}
								</Link>
							),
						})}
					</p>
				</form>
			</div>
		</div>
	);
}
