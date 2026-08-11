"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Building2, Hash, Phone, Briefcase } from "lucide-react";

import { Button } from "@/ui/components/ui/button";
import { Input } from "@/ui/components/ui/input";
import { Label } from "@/ui/components/ui/label";
import { buildStorefrontPath } from "@/lib/storefront-path";

/**
 * Alta de empresa para una cuenta que ya existe.
 *
 * Es el camino de quien se registró antes de que hubiera catálogo mayorista, y
 * el destino al que se envía a un usuario autenticado que todavía no tiene RUT
 * asociado. El alta en el registro (`/signup`) hace lo mismo en un solo paso.
 */
export function EmpresaForm() {
	const t = useTranslations("account");
	const params = useParams<{ locale: string; channel: string }>();
	const router = useRouter();

	const [razonSocial, setRazonSocial] = useState("");
	const [rut, setRut] = useState("");
	const [giro, setGiro] = useState("");
	const [telefono, setTelefono] = useState("");
	const [enviando, setEnviando] = useState(false);
	const [error, setError] = useState("");

	const enviar = async (e: React.FormEvent) => {
		e.preventDefault();
		setError("");

		if (!rut.trim() || !razonSocial.trim()) {
			setError(t("errors.empresaRequerida"));
			return;
		}

		setEnviando(true);
		try {
			const res = await fetch("/api/b2b/company", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ rut, razonSocial, giro, telefono }),
			});
			const dato = (await res.json()) as { ok?: boolean; mensaje?: string };

			if (!res.ok || !dato.ok) {
				setError(dato.mensaje || t("errors.empresaFallida"));
				return;
			}

			// `refresh()` antes de navegar: la puerta del catálogo se evalúa en el
			// servidor y sin esto el usuario volvería a caer en esta misma página.
			router.refresh();
			router.replace(buildStorefrontPath(params.locale, params.channel, "/products"));
		} catch {
			setError(t("errors.generic"));
		} finally {
			setEnviando(false);
		}
	};

	return (
		<div className="mx-auto mt-16 w-full max-w-md">
			<div className="rounded-lg border border-border bg-card p-8 shadow-sm">
				<div className="mb-6 text-center">
					<h1 className="text-balance text-h1">{t("empresa.title")}</h1>
					<p className="mt-2 text-sm text-muted-foreground">{t("empresa.subtitle")}</p>
				</div>

				<form onSubmit={(e) => void enviar(e)} className="space-y-4">
					{error ? (
						<div role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
							{error}
						</div>
					) : null}

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
								spellCheck={false}
								value={rut}
								onChange={(e) => setRut(e.target.value)}
								className="h-12 pl-10"
								required
							/>
						</div>
						<p className="text-xs text-muted-foreground">{t("signup.rutHint")}</p>
					</div>

					<div className="space-y-1.5">
						<Label htmlFor="giro" className="text-sm font-medium">
							{t("fields.giro")}
						</Label>
						<div className="relative">
							<Briefcase className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
							<Input
								id="giro"
								type="text"
								placeholder={t("placeholders.giro")}
								value={giro}
								onChange={(e) => setGiro(e.target.value)}
								className="h-12 pl-10"
							/>
						</div>
					</div>

					<div className="space-y-1.5">
						<Label htmlFor="telefono" className="text-sm font-medium">
							{t("fields.telefono")}
						</Label>
						<div className="relative">
							<Phone className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
							<Input
								id="telefono"
								type="tel"
								placeholder={t("placeholders.telefono")}
								autoComplete="tel"
								value={telefono}
								onChange={(e) => setTelefono(e.target.value)}
								className="h-12 pl-10"
							/>
						</div>
					</div>

					<Button type="submit" disabled={enviando} className="h-12 w-full">
						{enviando ? t("empresa.saving") : t("empresa.submit")}
					</Button>
				</form>
			</div>
		</div>
	);
}
