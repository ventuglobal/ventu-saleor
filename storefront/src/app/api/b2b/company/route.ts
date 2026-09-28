import { NextResponse, type NextRequest } from "next/server";

import { getHeaderAuthState } from "@/lib/auth/get-header-user";
import { rejectIfRateLimited } from "@/lib/auth/auth-rate-limit";
import { getEmpresa, registrarEmpresa } from "@/lib/b2b/company";
import { MENSAJE_EMPRESA_NO_DISPONIBLE } from "@/lib/b2b/errores";

/**
 * La empresa de **la sesión**, y su alta.
 *
 * El id de usuario nunca llega en el cuerpo: se resuelve desde la cookie de
 * sesión. Aceptarlo del cliente permitiría leer la empresa de otra persona, o
 * peor, asociarle una.
 */

/**
 * `autenticado` le dice al checkout si mostrar «inicia sesión» o «registra tu
 * empresa»: la sesión la decide el servidor, no el estado del navegador, que
 * puede ir atrasado.
 *
 * Si no se puede saber —Saleor sin responder la sesión, o la App B2B caída— se
 * contesta 503 en vez de «sin empresa»: una empresa ya registrada no debe ver
 * «registra tu empresa» por una caída.
 */
export async function GET() {
	const auth = await getHeaderAuthState();
	if (auth.status === "guest") {
		return NextResponse.json({ registrada: false, autenticado: false });
	}
	if (auth.status !== "authenticated") {
		return NextResponse.json({ mensaje: MENSAJE_EMPRESA_NO_DISPONIBLE }, { status: 503 });
	}

	const empresa = await getEmpresa(auth.user.id);
	if (!empresa.registrada && empresa.error) {
		return NextResponse.json({ mensaje: MENSAJE_EMPRESA_NO_DISPONIBLE }, { status: 503 });
	}
	return NextResponse.json({ ...empresa, autenticado: true });
}

type AltaRequest = {
	rut?: string;
	razonSocial?: string;
	giro?: string;
	telefono?: string;
};

export async function POST(request: NextRequest) {
	// El alta consulta el RUT contra Saleor; sin límite, este endpoint sirve para
	// averiguar qué RUT están registrados.
	const limitado = rejectIfRateLimited(request, "b2b-company", {
		limit: 10,
		windowMs: 60 * 60 * 1000,
	});
	if (limitado) return limitado;

	const auth = await getHeaderAuthState();
	if (auth.status !== "authenticated") {
		return NextResponse.json({ mensaje: "Inicia sesión para registrar tu empresa." }, { status: 401 });
	}

	let cuerpo: AltaRequest;
	try {
		cuerpo = (await request.json()) as AltaRequest;
	} catch {
		return NextResponse.json({ mensaje: "Solicitud inválida." }, { status: 400 });
	}

	const rut = cuerpo.rut?.trim();
	const razonSocial = cuerpo.razonSocial?.trim();
	if (!rut || !razonSocial) {
		return NextResponse.json({ mensaje: "El RUT y la razón social son obligatorios." }, { status: 400 });
	}

	// El dígito verificador lo valida la App B2B: una sola implementación del
	// módulo 11, y del lado que no se puede saltar.
	const resultado = await registrarEmpresa(auth.user.id, {
		rut,
		razonSocial,
		giro: cuerpo.giro,
		telefono: cuerpo.telefono,
	});

	if (!resultado.ok) {
		// `mensaje` ya viene traducido por `registrarEmpresa`; el detalle crudo de
		// la App B2B quedó en el log del servidor.
		const { mensaje, code } = resultado;
		return NextResponse.json({ mensaje, ...(code ? { code } : {}) }, { status: resultado.status });
	}

	return NextResponse.json({ ok: true, rut: resultado.rut });
}
