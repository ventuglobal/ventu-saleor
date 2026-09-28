"use client";

import { useCallback, useEffect, useState, type FC, type ReactNode } from "react";
import Link from "next/link";
import { CreditCard, Landmark, FileClock, Loader2, Building2, Clock, LogIn } from "lucide-react";

import { Button, buttonClassName } from "@/ui/components/ui/button";
import { navigateToOrderConfirmation } from "@/checkout/lib/payment/navigate-to-order";
import { guardarInstruccionesPago } from "@/checkout/lib/payment/instrucciones-pago";
import {
	estadoMediosPago,
	estadoTrasRechazoDePedido,
	medioPreseleccionado,
	type DatosEmpresa,
	type EstadoMediosPago,
} from "@/checkout/lib/payment/estado-medios-pago";
import { useCheckoutBrowseLocale } from "@/checkout/providers/checkout-browse";
import { EMPRESA_EN_REVISION, MENSAJE_PEDIDO_GENERICO } from "@/lib/b2b/errores";
import { buildStorefrontPath } from "@/lib/storefront-path";

/**
 * Medios de pago de Ventu B2B.
 *
 * En un canal de empresa es la única caja del paso de pago: un pedido mayorista
 * se cierra contra una promesa de pago —transferencia, Cheke Maxxa a 30 días—
 * y no contra una autorización de tarjeta. Por eso nunca queda vacía: si la
 * empresa todavía no puede comprar, dice qué falta (iniciar sesión, registrar
 * la empresa o esperar la revisión) y no ofrece el botón del pedido.
 *
 * Los medios que todavía no están conectados **se muestran igual**, deshabilitados
 * y con el motivo. Una vitrina que solo lista lo que funciona no le dice a la
 * empresa qué va a poder usar, ni por qué le conviene pedir crédito.
 */

type MediosPagoVentuProps = {
	canal: string;
	/**
	 * Guarda la dirección de facturación del formulario en el checkout. Se espera
	 * antes de crear el pedido porque la orden la copia del checkout; si falla,
	 * el paso de pago marca los campos y el pedido no se envía.
	 */
	guardarFacturacion: () => Promise<boolean>;
};

type RespuestaPedido = {
	order_id?: string;
	numero?: string;
	instrucciones_pago?: string | null;
	/** Ya traducido por la ruta; el error crudo quedó en el log del servidor. */
	mensaje?: string;
	code?: string;
};

/** Pedido creado cuyas instrucciones no se pudieron dejar para la confirmación. */
type PedidoConInstrucciones = { orderId: string; numero?: string; instrucciones: string };

const ICONOS: Record<string, typeof CreditCard> = {
	tarjeta_credito: CreditCard,
	tarjeta_debito: CreditCard,
	transferencia: Landmark,
	maxxa_30: FileClock,
};

const MOTIVOS: Record<string, string> = {
	sin_credito: "Requiere crédito aprobado por Maxxa",
	no_operativo: "Próximamente",
	pendiente_aprobacion: "Disponible cuando aprobemos tu empresa",
};

const DETALLE: Record<string, string> = {
	transferencia: "Te enviamos los datos bancarios y el pedido queda reservado.",
	maxxa_30: "Pagas a 30 días. El pedido se despacha de inmediato.",
};

/** Los pasos siguientes son enlaces a la tienda, con aspecto de botón secundario. */
const ENLACE = buttonClassName({ variant: "outline-solid", asLink: true });

/** Encabezado con la empresa, para que se vea con qué RUT se va a comprar. */
function Encabezado({ empresa }: { empresa?: DatosEmpresa }) {
	return (
		<div>
			<h2 className="text-base font-semibold text-foreground">Medio de pago</h2>
			{empresa?.razon_social ? (
				<p className="text-sm text-muted-foreground">
					{empresa.razon_social}
					{empresa.rut ? ` · ${empresa.rut}` : null}
				</p>
			) : null}
		</div>
	);
}

/** Un estado sin botón de pedido: qué pasa y, si hay, qué hacer. */
function Aviso({
	icono: Icono,
	children,
	accion,
}: {
	icono: typeof CreditCard;
	children: ReactNode;
	accion?: ReactNode;
}) {
	return (
		<div className="flex items-start gap-3 rounded-lg border border-border bg-muted/40 p-4" role="status">
			<Icono aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
			<div className="flex-1 space-y-3">
				<p className="text-sm text-foreground">{children}</p>
				{accion}
			</div>
		</div>
	);
}

export const MediosPagoVentu: FC<MediosPagoVentuProps> = ({ canal, guardarFacturacion }) => {
	const locale = useCheckoutBrowseLocale();
	/** `null` mientras carga. */
	const [estado, setEstado] = useState<EstadoMediosPago | null>(null);
	/** Sube con «Reintentar» para volver a pedir la empresa. */
	const [intento, setIntento] = useState(0);
	const [elegido, setElegido] = useState<string>("");
	const [enviando, setEnviando] = useState(false);
	const [error, setError] = useState("");
	const [creado, setCreado] = useState<PedidoConInstrucciones | null>(null);

	useEffect(() => {
		let vigente = true;

		void (async () => {
			let siguiente: EstadoMediosPago;
			try {
				const res = await fetch("/api/b2b/company", { cache: "no-store" });
				const dato: unknown = await res.json().catch(() => null);
				siguiente = estadoMediosPago(res.status, dato);
			} catch {
				siguiente = { tipo: "error" };
			}
			if (!vigente) return;

			setEstado(siguiente);
			setElegido(medioPreseleccionado(siguiente));
		})();

		return () => {
			vigente = false;
		};
	}, [intento]);

	const reintentar = useCallback(() => {
		setEstado(null);
		setIntento((n) => n + 1);
	}, []);

	const comprar = useCallback(async () => {
		if (!elegido || estado?.tipo !== "aprobada") return;
		setEnviando(true);
		setError("");

		try {
			// Primero la facturación: un pedido ya creado no se puede corregir
			// desde aquí, y la factura saldría con una dirección equivocada.
			const facturacionOk = await guardarFacturacion();
			if (!facturacionOk) {
				setError("Revisa la dirección de facturación antes de realizar el pedido.");
				return;
			}

			const res = await fetch("/api/b2b/pedido", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ canal, metodoPago: elegido }),
			});
			const dato = (await res.json().catch(() => ({}))) as RespuestaPedido;

			if (!res.ok || !dato.order_id) {
				// La empresa pudo volver a revisión, o la sesión expirar, desde que
				// se cargó la caja: se cambia de estado en vez de dejar un botón que
				// va a fallar igual. El aviso del estado nuevo ya explica qué pasa,
				// así que el mensaje no se repite abajo.
				const cambio = estadoTrasRechazoDePedido(estado, res.status, dato.code);
				if (cambio) {
					setEstado(cambio);
					setElegido("");
					return;
				}
				setError(dato.mensaje || MENSAJE_PEDIDO_GENERICO);
				return;
			}

			// Las instrucciones (datos de la transferencia, por ejemplo) se dejan
			// para la confirmación. Si no hay dónde dejarlas se muestran aquí antes
			// de salir: perderlas obligaría a quien compra a pedirlas por otro lado.
			const instrucciones = typeof dato.instrucciones_pago === "string" ? dato.instrucciones_pago : null;
			if (instrucciones && !guardarInstruccionesPago(dato.order_id, instrucciones)) {
				setCreado({ orderId: dato.order_id, numero: dato.numero, instrucciones });
				return;
			}

			navigateToOrderConfirmation(dato.order_id);
		} catch {
			setError("No se pudo crear el pedido. Vuelve a intentarlo.");
		} finally {
			setEnviando(false);
		}
	}, [canal, elegido, estado, guardarFacturacion]);

	if (creado) {
		return (
			<section
				className="space-y-4 rounded-lg border border-border p-4"
				data-testid="medios-pago-ventu"
				role="status"
			>
				<div>
					<h2 className="text-base font-semibold text-foreground">
						{creado.numero ? `Pedido n.º ${creado.numero} recibido` : "Pedido recibido"}
					</h2>
					<p className="text-sm text-muted-foreground">Guarda estos datos para completar el pago.</p>
				</div>
				{/* Texto plano: React escapa el contenido y `whitespace-pre-line`
				    respeta los saltos de línea que manda la App B2B. */}
				<p className="whitespace-pre-line text-sm text-foreground">{creado.instrucciones}</p>
				<div className="flex flex-col items-stretch md:items-end">
					<Button
						type="button"
						onClick={() => navigateToOrderConfirmation(creado.orderId)}
						className="h-12 px-8 md:min-w-[220px]"
					>
						Ver mi pedido
					</Button>
				</div>
			</section>
		);
	}

	if (!estado) {
		return (
			<section className="space-y-4" data-testid="medios-pago-ventu" aria-busy="true">
				<Encabezado />
				<p className="flex items-center gap-2 text-sm text-muted-foreground">
					<Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
					Cargando los medios de pago de tu empresa…
				</p>
			</section>
		);
	}

	if (estado.tipo !== "aprobada") {
		return (
			<section className="space-y-4" data-testid="medios-pago-ventu" data-estado={estado.tipo}>
				<Encabezado empresa={"empresa" in estado ? estado.empresa : undefined} />
				{estado.tipo === "invitado" ? (
					<Aviso
						icono={LogIn}
						accion={
							<Link href={buildStorefrontPath(locale, canal, "/login")} className={ENLACE}>
								Iniciar sesión
							</Link>
						}
					>
						Los pedidos de empresa se hacen con tu cuenta. Inicia sesión para ver los medios de pago de tu
						empresa.
					</Aviso>
				) : estado.tipo === "sin_empresa" ? (
					<Aviso
						icono={Building2}
						accion={
							<Link href={buildStorefrontPath(locale, canal, "/empresa")} className={ENLACE}>
								Registrar empresa
							</Link>
						}
					>
						Tu cuenta todavía no tiene una empresa registrada. Regístrala con su RUT para poder hacer pedidos.
					</Aviso>
				) : estado.tipo === "en_revision" ? (
					<Aviso icono={Clock}>{EMPRESA_EN_REVISION}</Aviso>
				) : estado.tipo === "sin_medios" ? (
					<Aviso icono={CreditCard}>
						Tu empresa todavía no tiene medios de pago habilitados. Escríbele al equipo de Ventu para
						activarlos.
					</Aviso>
				) : (
					<Aviso
						icono={CreditCard}
						accion={
							<Button type="button" variant="outline-solid" onClick={reintentar}>
								Reintentar
							</Button>
						}
					>
						No pudimos cargar los medios de pago de tu empresa. Intenta de nuevo en unos segundos.
					</Aviso>
				)}
			</section>
		);
	}

	const { empresa } = estado;

	return (
		<section className="space-y-4" data-testid="medios-pago-ventu" data-estado={estado.tipo}>
			<Encabezado empresa={empresa} />

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
