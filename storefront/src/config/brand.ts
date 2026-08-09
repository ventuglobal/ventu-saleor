/**
 * Brand Configuration
 *
 * Centralized branding settings for the storefront.
 * Update these values when customizing for a new store.
 *
 * @example
 * ```tsx
 * import { brandConfig } from "@/config/brand";
 *
 * <title>{brandConfig.siteName}</title>
 * <p>© {new Date().getFullYear()} {brandConfig.copyrightHolder}</p>
 * ```
 */

export const brandConfig = {
	/** Site name used in titles, metadata, and headers */
	siteName: "Ventu",

	/** Legal entity name for copyright notices */
	copyrightHolder: "Ventu",

	/** Organization name for structured data (JSON-LD) */
	organizationName: "Ventu",

	/** Default brand name for products without a brand */
	defaultBrand: "Ventu",

	/** Tagline/description for the store */
	tagline: "Tecnología y suministros para tu empresa, con despacho en todo Chile.",

	/** Homepage meta description */
	description: "Catálogo mayorista de tecnología, redes y suministros. Precios con IVA incluido y despacho a todo Chile.",

	/** Logo aria-label for accessibility */
	logoAriaLabel: "Ventu",

	/** Title template - %s will be replaced with page title */
	titleTemplate: "%s | Ventu",

	/** Social media handles */
	social: {
		/** Twitter/X handle (without @) - set to null to disable */
		twitter: null as string | null,
		/** Instagram handle (without @) - set to null to disable */
		instagram: null as string | null,
		/** Facebook page URL - set to null to disable */
		facebook: null as string | null,
	},
} as const;

/**
 * Helper to format page title using brand template.
 */
export function formatPageTitle(title: string): string {
	return brandConfig.titleTemplate.replace("%s", title);
}

/**
 * Get copyright text with specified year.
 * Use CopyrightText component for dynamic year in Server Components.
 */
export function getCopyrightText(year: number = new Date().getFullYear()): string {
	return `© ${year} ${brandConfig.copyrightHolder}. Todos los derechos reservados.`;
}
