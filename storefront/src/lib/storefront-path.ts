/**
 * Helpers for `/{locale}/{channel}/…` browse URLs (ADR 0001).
 *
 * **Ventu — URLs canónicas en la raíz.** El mercado por defecto (locale +
 * channel configurados) vive en la raíz: `/products/foo`, no
 * `/es/retail-cl/products/foo`. Los demás mercados conservan el prefijo
 * explícito. El motivo es la migración: el sitio actual (Shopify) sirve
 * `/products/<handle>` y `/collections/<handle>`, así que al reemplazarlo las
 * URLs públicas —y con ellas el SEO y los enlaces existentes— se conservan.
 *
 * El enrutado interno de Next sigue siendo `[locale]/[channel]`; el middleware
 * reescribe (sin redirigir) la forma corta hacia él.
 */

import { DefaultChannelSlug } from "@/app/config";
import { getDefaultLocaleSlug, isLocaleSlug } from "@/config/locale";

export type StorefrontPathPrefix = {
	locale: string;
	channel: string;
	/** Path after channel, including leading slash — e.g. `/products/foo` or `` for homepage */
	suffix: string;
};

/** ¿Este par locale+channel es el mercado por defecto (el que vive en la raíz)? */
export function isDefaultMarket(locale: string, channel: string): boolean {
	return locale === getDefaultLocaleSlug() && channel === DefaultChannelSlug;
}

export function buildStorefrontPath(locale: string, channel: string, suffix = ""): string {
	const normalizedSuffix = suffix.startsWith("/") || suffix === "" ? suffix : `/${suffix}`;
	if (isDefaultMarket(locale, channel)) {
		return normalizedSuffix === "" ? "/" : normalizedSuffix;
	}
	return `/${encodeURIComponent(locale)}/${encodeURIComponent(channel)}${normalizedSuffix}`;
}

/**
 * Parse a pathname into locale + channel + suffix.
 *
 * Acepta las dos formas: la prefijada (`/es/retail-cl/products/foo`) y la corta
 * del mercado por defecto (`/products/foo`), que resuelve al locale y channel
 * configurados. Sin esto, la forma corta se interpretaría como
 * locale=`products`, channel=`foo`.
 */
export function parseStorefrontPathname(pathname: string): StorefrontPathPrefix | null {
	const segments = pathname.split("/").filter(Boolean);

	const [maybeLocale, maybeChannel, ...rest] = segments;
	if (maybeLocale && isLocaleSlug(decodeURIComponent(maybeLocale)) && maybeChannel) {
		return {
			locale: decodeURIComponent(maybeLocale),
			channel: decodeURIComponent(maybeChannel),
			suffix: rest.length > 0 ? `/${rest.join("/")}` : "",
		};
	}

	// Forma corta: mercado por defecto en la raíz.
	const defaultChannel = DefaultChannelSlug;
	if (!defaultChannel) return null;
	return {
		locale: getDefaultLocaleSlug(),
		channel: defaultChannel,
		suffix: segments.length > 0 ? `/${segments.join("/")}` : "",
	};
}

export function replaceStorefrontChannel(pathname: string, newChannel: string): string | null {
	const parsed = parseStorefrontPathname(pathname);
	if (!parsed) return null;
	return buildStorefrontPath(parsed.locale, newChannel, parsed.suffix);
}

export function replaceStorefrontLocale(pathname: string, newLocale: string): string | null {
	const parsed = parseStorefrontPathname(pathname);
	if (!parsed) return null;
	return buildStorefrontPath(newLocale, parsed.channel, parsed.suffix);
}

/** Strip `/{locale}/{channel}` for nav active-state matching. */
export function stripStorefrontPrefix(pathname: string, locale: string, channel: string): string {
	const prefix = `/${locale}/${channel}`;
	if (pathname === prefix || pathname === `${prefix}/`) {
		return "/";
	}
	if (pathname.startsWith(`${prefix}/`)) {
		return pathname.slice(prefix.length);
	}
	// La forma corta ya viene sin prefijo.
	return pathname;
}
