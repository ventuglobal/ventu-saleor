import { formatPrice } from "@/config/locale";
import type { Tramo } from "@/lib/b2b/tramos";

type TramosTableProps = {
	tramos: Tramo[];
	currency: string;
	locale: string;
	/** RUT de la empresa: explica por qué esta tabla está a la vista. */
	rut: string;
	labels: {
		title: string;
		caption: string;
		from: string;
		unitPrice: string;
		discount: string;
		unit: string;
		units: string;
	};
};

/**
 * Tabla de precios por volumen de la ficha de producto.
 *
 * Se renderiza únicamente cuando la App B2B resolvió que la sesión pertenece a
 * una empresa registrada: para cualquier otra sesión el componente no llega a
 * existir, así que la escalera tampoco viaja en el HTML.
 *
 * Es informativa. El precio de compra lo resuelve la cantidad del carrito —el
 * tramo aplica a **todas** las unidades de la línea, no solo a las que exceden
 * el mínimo—, que es el modelo de distribución mayorista y el del sitio actual.
 */
export function TramosTable({ tramos, currency, locale, rut, labels }: TramosTableProps) {
	if (tramos.length === 0) return null;

	const base = tramos[0].precio_unitario;

	return (
		<section className="rounded-lg border border-border bg-muted/30 p-4" data-testid="tramos-table">
			<div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
				<h2 className="text-sm font-semibold text-foreground">{labels.title}</h2>
				<span className="font-mono text-xs text-muted-foreground">{rut}</span>
			</div>

			<div className="overflow-x-auto">
				<table className="w-full border-collapse text-sm">
					<thead>
						<tr className="text-xs uppercase tracking-wide text-muted-foreground">
							<th scope="col" className="pb-2 pr-3 text-left font-medium">
								{labels.from}
							</th>
							<th scope="col" className="pb-2 pl-3 text-right font-medium">
								{labels.unitPrice}
							</th>
							<th scope="col" className="pb-2 pl-3 text-right font-medium">
								{labels.discount}
							</th>
						</tr>
					</thead>
					<tbody>
						{tramos.map((tramo) => {
							// Redondeado: el porcentaje orienta la decisión de compra, el
							// monto es el dato exacto.
							const descuento = base > 0 ? Math.round((1 - tramo.precio_unitario / base) * 100) : 0;

							return (
								<tr key={tramo.desde} className="border-t border-border/60">
									<td className="py-2 pr-3 tabular-nums">
										{tramo.desde} {tramo.desde === 1 ? labels.unit : labels.units}
									</td>
									<td className="py-2 pl-3 text-right font-medium tabular-nums">
										{formatPrice(tramo.precio_unitario, currency, locale)}
									</td>
									<td className="py-2 pl-3 text-right tabular-nums text-muted-foreground">
										{descuento > 0 ? `−${descuento}%` : "—"}
									</td>
								</tr>
							);
						})}
					</tbody>
				</table>
			</div>

			<p className="mt-3 text-xs text-muted-foreground">{labels.caption}</p>
		</section>
	);
}
