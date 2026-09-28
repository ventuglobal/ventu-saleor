"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/**
 * En `/empresa` el aviso repetiría lo que la página ya pide, con un enlace a sí
 * misma. La ruta se lee en el cliente porque el layout no la conoce, y va dentro
 * del `Suspense` del aviso: `usePathname()` no puede prerenderizarse.
 */
export function OcultoEnEmpresa({ children }: { children: ReactNode }) {
	const pathname = usePathname();
	return pathname?.endsWith("/empresa") ? null : children;
}
