import { brandConfig } from "@/config/brand";
import { STOREFRONT_CONTENT_VERSION, type StorefrontContent } from "@/lib/content/types";

/**
 * Code fallback for all storefront marketing copy.
 * Saleor PageType overrides merge on top when CONTENT_PROVIDER=saleor.
 *
 * Copy editorial en español de Chile (es-CL) — export a Configurator: pnpm content:export-seed
 */
export const defaultStorefrontContent = {
	version: STOREFRONT_CONTENT_VERSION,
	// Single source of truth for channel-wide facts. Copy references these via
	// `{freeShippingThreshold}` / `{returnsWindowDays}` tokens instead of baking the
	// numbers into strings, so the cart math, announcement, and trust labels never drift.
	policies: {
		shipping: {
			// PROVISIONAL — pendiente de confirmar con el negocio.
			// El valor heredado del storefront de ejemplo era 75, pensado en dólares.
			// En una tienda que factura en CLP eso son 75 pesos: cualquier pedido
			// calificaría y Ventu quedaría prometiendo despacho gratis en todo.
			// Se deja un monto plausible en pesos; `null` no sirve como valor por
			// defecto porque el exportador del seed exige un número.
			freeShippingThreshold: 50000,
		},
		returns: {
			windowDays: 30,
		},
	},
	chrome: {
		announcementBar: {
			id: "",
			message: "Despacho gratis en compras sobre {freeShippingThreshold}",
			href: null,
			linkLabel: null,
			dismissible: true,
		},
		nav: {
			allProductsLabel: "Todos",
			viewAllLabel: "Ver todo en {label}",
		},
	},
	surfaces: {
		homepage: {
			hero: {
				heading: "Tecnología y suministros para tu empresa",
				subheading: brandConfig.tagline,
				primaryCtaLabel: "Ver catálogo",
			},
			featuredCollection: {
				heading: "Productos destacados",
				collectionSlug: "featured-products",
				limit: 8,
			},
			categories: {
				heading: "Compra por categoría",
			},
			photoCredits: [],
			brandStory: {
				heading: "Abastecemos a empresas de todo Chile",
				paragraphs: [
					"Ventu conecta a empresas con un catálogo mayorista de tecnología, redes y suministros, con precios claros y despacho a todo el país.",
					"Compra en línea o cotiza con un ejecutivo: en ambos casos el pedido queda registrado, facturado y con seguimiento.",
				],
			},
			values: {
				heading: "Por qué comprar en Ventu",
				columns: [
					{
						title: "Stock real",
						text: "Publicamos lo que tenemos disponible, con la cantidad a la vista antes de comprar.",
					},
					{
						title: "Despacho a todo Chile",
						text: "Despachamos a regiones con seguimiento desde que confirmas el pedido hasta la entrega.",
					},
					{
						title: "Factura y crédito",
						text: "Emitimos factura a tu RUT y puedes solicitar condiciones de pago a plazo.",
					},
				],
				columnsDesktop: 3,
			},
			editorial: {
				heading: "Pensado para quien compra por volumen",
				paragraphs: [
					"Precios por tramo de cantidad: mientras más llevas, menor es el precio unitario.",
				],
				imagePosition: "right",
				ctaLabel: "Ver categorías",
				image: null,
				imageAlt: "",
			},
		},
		products: {
			title: "Todos los productos",
			description: "Recorre todo el catálogo de Ventu: tecnología, redes y suministros.",
		},
		cart: {
			empty: {
				title: "Tu carro está vacío",
				body: "Todavía no has agregado ningún producto.",
				ctaLabel: "Comenzar a comprar",
			},
			trust: {
				freeShippingPrefix: "Despacho gratis sobre",
				returnsLabel: "Devoluciones en {returnsWindowDays} días",
			},
			drawer: {
				title: "Tu carro",
				addForFreeShipping: "Agrega {amount} más y el despacho es gratis",
				freeShippingQualified: "¡Tu despacho es gratis!",
			},
		},
		checkout: {
			emptyCart: {
				title: "Tu carro está vacío",
				body: "Todavía no has agregado ningún producto.",
				startShoppingLabel: "Comenzar a comprar",
				goBackLabel: "Volver",
			},
			emptySession: {
				title: "Your cart is empty",
				message: "Agrega productos desde la tienda y vuelve aquí para completar tu compra.",
			},
			marketingOptInLabel: "Quiero recibir novedades y ofertas por correo",
			trust: {
				secureCheckout: "Compra segura",
				stripeProcessor: "Pagos procesados por Stripe",
			},
		},
	},
} satisfies StorefrontContent;
