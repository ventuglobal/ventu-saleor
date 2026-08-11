"use client";

import { useCallback, useEffect, useState, type FC } from "react";
import { CreditCard, Landmark, FileClock, Loader2 } from "lucide-react";

import { Button } from "@/ui/components/ui/button";
import { navigateToOrderConfirmation } from "@/checkout/lib/payment/navigate-to-order";

/**
 * Medios de pago de Ventu B2B.
 *
 * Reemplaza la caja de pasarelas cuando quien compra es una empresa registrada:
 * un pedido mayorista se cierra contra una promesa de pago —transferencia,
 * Cheke Maxxa a 30 días— y no contra una autorización de tarjeta.
 *
 * Los medios que todavía no están conectados **se muestran igual**, deshabilitados
 * y con el motivo. Una vitrina que solo lista lo que funciona no le dice a la
 * empresa qué va a poder usar, ni por qué le conviene pedir crédito.
 */

type MedioPago = {
	codigo: string;
	etiqueta: string;
	diferido: boolean;
	habilitado: boolean;
	motivo?: string;
};

type RespuestaEmpresa = {
	registrada: boolean;
	razon_social?: string;
	rut?: string;
	medios_pago?: MedioPago[];
};

type MediosPagoVentuProps = {
	canal: string;
	/** Avisa al paso de pago para que oculte la caja de pasarelas y su botón. */
	onDisponible?: (disponible: boolean) => void;
};

const ICONOS: Record<string, typeof CreditCard> = {
	tarjeta_credito: CreditCard,
	tarjeta_debito: CreditCard,
	transferencia: Landmark,
	maxxa_30: FileClock,
};

const MOTIVOS: Record<string, string> = {
	sin_credito: "Requiere crédito aprobado por Maxxa",
	no_operativo: "Próximamente",
};

const DETALLE: Record<string, string> = {
	transferencia: "Te enviamos los datos bancarios y el pedido queda reservado.",
	maxxa_30: "Pagas a 30 días. El pedido se despacha de inmediato.",
};

export const MediosPagoVentu: FC<MediosPagoVentuProps> = ({ canal, onDisponible }) => {
	const [empresa, setEmpresa] = useState<RespuestaEmpresa | null>(null);
	const [elegido, setElegido] = useState<string>("");
	const [enviando, setEnviando] = useState(false);
	const [error, setError] = useState("");

	useEffect(() => {
		let vigente = true;

		void (async () => {
			try {
				const res = await fetch("/api/b2b/company", { cache: "no-store" });
				const dato = (await res.json()) as RespuestaEmpresa;
				if (!vigente) return;

				setEmpresa(dato);
				onDisponible?.(Boolean(dato.registrada));

				// Preselecciona el primer medio usable: en la mayoría de los casos
				// hay uno solo y obligar a elegirlo no aporta nada.
				const primero = dato.medios_pago?.find((m) => m.habilitado);
				if (primero) setElegido(primero.codigo);
			} catch {
				if (vigente) onDisponible?.(false);
			}
		})();

		return () => {
			vigente = false;
		};
	}, [onDisponible]);

	const comprar = useCallback(async () => {
		if (!elegido) return;
		setEnviando(true);
		setError("");

		try {
			const res = await fetch("/api/b2b/pedido", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ canal, metodoPago: elegido }),
			});
			const dato = (await res.json()) as { order_id?: string; mensaje?: string };

			if (!res.ok || !dato.order_id) {
				setError(dato.mensaje || "No se pudo crear el pedido.");
				return;
			}

			navigateToOrderConfirmation(dato.order_id);
		} catch {
			setError("No se pudo crear el pedido. Vuelve a intentarlo.");
		} finally {
			setEnviando(false);
		}
	}, [canal, elegido]);

	if (!empresa?.registrada || !empresa.medios_pago?.length) {
		return null;
	}

	return (
		<section className="space-y-4" data-testid="medios-pago-ventu">
			<div>
				<h2 className="text-base font-semibold text-foreground">Medio de pago</h2>
				{empresa.razon_social ? (
					<p className="text-sm text-muted-foreground">
						{empresa.razon_social} · {empresa.rut}
					</p>
				) : null}
			</div>

			<ul className="space-y-2">
				{empresa.medios_pago.map((medio) => {
					const Icono = ICONOS[medio.codigo] ?? CreditCard;
					const seleccionado = elegido === medio.codigo;

					return (
						<li key={medio.codigo}>
							<label
								className={[
									"flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition-colors",
									seleccionado ? "border-foreground bg-muted/40" : "border-border",
									medio.habilitado ? "hover:border-foreground/60" : "cursor-not-allowed opacity-60",
								].join(" ")}
							>
								<input
									type="radio"
									name="medio-pago-ventu"
									value={medio.codigo}
									checked={seleccionado}
									disabled={!medio.habilitado || enviando}
									onChange={() => setElegido(medio.codigo)}
									className="mt-1 h-4 w-4 accent-foreground"
								/>
								<Icono aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
								<span className="flex-1">
									<span className="block text-sm font-medium text-foreground">{medio.etiqueta}</span>
									{medio.habilitado ? (
										DETALLE[medio.codigo] ? (
											<span className="block text-sm text-muted-foreground">{DETALLE[medio.codigo]}</span>
										) : null
									) : (
										<span className="block text-sm text-muted-foreground">
											{MOTIVOS[medio.motivo ?? ""] ?? "No disponible"}
										</span>
									)}
								</span>
							</label>
						</li>
					);
				})}
			</ul>

			{error ? (
				<p className="text-sm text-destructive" role="alert">
					{error}
				</p>
			) : null}

			<div className="flex flex-col items-stretch gap-2 md:items-end">
				<Button
					type="button"
					onClick={() => void comprar()}
					disabled={!elegido || enviando}
					className="h-12 px-8 md:min-w-[220px]"
				>
					{enviando ? (
						<span className="flex items-center gap-2">
							<Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
							Creando el pedido…
						</span>
					) : (
						"Realizar pedido"
					)}
				</Button>
				<p className="text-xs text-muted-foreground md:text-right">
					El pedido queda registrado como pendiente de pago.
				</p>
			</div>
		</section>
	);
};
