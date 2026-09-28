import { NextRequest, NextResponse } from "next/server";
import { rejectIfRateLimited } from "@/lib/auth/auth-rate-limit";
import { isAllowedRedirectUrl } from "@/lib/auth/validate-redirect-url";
import { executeRawGraphQL } from "@/lib/graphql";
import { esCanalB2B } from "@/lib/b2b/canales";
import { registrarEmpresa, type AltaEmpresa } from "@/lib/b2b/company";
import { EMPRESA_PENDIENTE_REGISTRO, empresaPendienteTrasRechazo, mensajeDeCuenta } from "@/lib/b2b/errores";
import { empresaDelRegistro } from "@/lib/b2b/registro";

const REGISTER_MUTATION = `
  mutation AccountRegister($input: AccountRegisterInput!) {
    accountRegister(input: $input) {
      user {
        id
        email
      }
      errors {
        field
        message
        code
      }
    }
  }
`;

/**
 * Solo para saber el id de la cuenta recién creada: en Saleor 3.23
 * `accountRegister` lo devuelve vacío. Se pide `user { id }` y nada más — ni
 * `token` ni `refreshToken` ni `csrfToken` —, así que ningún token viaja de
 * vuelta en el cuerpo. La cookie de refresh que Saleor pueda poner en la
 * respuesta queda en este `fetch` del servidor y nunca llega al navegador: el
 * registro no inicia sesión.
 */
const TOKEN_CREATE_MUTATION = `
  mutation TokenCreateRegistro($email: String!, $password: String!) {
    tokenCreate(email: $email, password: $password) {
      user {
        id
      }
      errors {
        field
        code
      }
    }
  }
`;

interface RegisterRequest {
	email: string;
	password: string;
	firstName?: string;
	lastName?: string;
	channel: string;
	redirectUrl: string;
	/**
	 * Alta de empresa en el mismo paso: quien compra al por mayor compra con RUT.
	 * Solo se considera en canales de empresa; en retail se ignora.
	 */
	rut?: string;
	razonSocial?: string;
	giro?: string;
	telefono?: string;
}

interface AccountRegisterResult {
	accountRegister?: {
		user?: { id: string; email: string };
		errors?: Array<{ field?: string | null; message: string; code?: string | null }>;
	};
}

interface TokenCreateResult {
	tokenCreate?: {
		user?: { id: string } | null;
		errors?: Array<{ field?: string | null; code?: string | null }>;
	} | null;
}

/**
 * Qué pasó con la empresa en el registro. `pendiente` le dice al formulario que
 * la cuenta sí quedó creada y que la empresa se completa en /empresa.
 */
type EmpresaRegistro = { ok: true } | { ok: false; pendiente: true; mensaje: string; code?: string };

function errorDeCuenta(code: string, status: number, message = mensajeDeCuenta(code)) {
	return NextResponse.json({ errors: [{ message, code }] }, { status });
}

/**
 * El id de la cuenta recién creada, probando el correo y la contraseña que
 * acaba de elegir. Es la misma prueba que un inicio de sesión: quien llega aquí
 * con una cuenta que ya existía solo obtiene su id si conoce la contraseña.
 *
 * `null` si Saleor no deja entrar todavía —lo normal mientras pida confirmar el
 * correo (`ACCOUNT_NOT_CONFIRMED`)— o no contesta. Al log van solo el tipo de
 * falla y los códigos: nunca el correo, la contraseña ni el token.
 */
async function idDeLaCuentaNueva(email: string, password: string): Promise<string | null> {
	const result = await executeRawGraphQL<TokenCreateResult>({
		query: TOKEN_CREATE_MUTATION,
		variables: { email, password },
	});

	if (!result.ok) {
		console.warn(
			"(b2b) No se pudo resolver la cuenta nueva para el alta de empresa:",
			result.error.type,
			result.error.statusCode ?? "",
			result.error.codes?.join(",") ?? "",
		);
		return null;
	}

	const tokenCreate = result.data.tokenCreate;
	if (tokenCreate?.errors?.length) {
		console.warn(
			"(b2b) Saleor no dejó entrar a la cuenta nueva; el alta de empresa queda pendiente:",
			tokenCreate.errors.map((e) => e.code ?? "SIN_CODIGO").join(","),
		);
		return null;
	}

	return tokenCreate?.user?.id || null;
}

/**
 * Alta de la empresa de una cuenta recién creada.
 *
 * Si falla, la cuenta igual quedó creada — deshacerla sería peor: el correo ya
 * está tomado y quien se registra no podría reintentar. Se devuelve `pendiente`
 * con el paso siguiente, y la empresa se completa en /empresa con la sesión.
 *
 * Sobre enumerar correos: si Saleor oculta que el correo ya existía y responde
 * éxito, `tokenCreate` con una contraseña ajena falla igual que una cuenta sin
 * confirmar, y ambas terminan en el mismo `pendiente` con el mismo mensaje. Solo
 * quien conoce la contraseña llega a `ok`, y eso ya lo sabría iniciando sesión.
 */
async function registrarEmpresaDeCuentaNueva(
	email: string,
	password: string,
	datos: AltaEmpresa,
): Promise<EmpresaRegistro> {
	const userId = await idDeLaCuentaNueva(email, password);
	if (!userId) return { ok: false, pendiente: true, mensaje: EMPRESA_PENDIENTE_REGISTRO };

	const alta = await registrarEmpresa(userId, datos);
	if (alta.ok) return { ok: true };

	// `registrarEmpresa` ya dejó el detalle crudo en el log y trae el motivo
	// traducido.
	return {
		ok: false,
		pendiente: true,
		mensaje: empresaPendienteTrasRechazo(alta.mensaje),
		...(alta.code ? { code: alta.code } : {}),
	};
}

export async function POST(request: NextRequest) {
	const rateLimited = rejectIfRateLimited(request, "register", { limit: 5, windowMs: 60 * 60 * 1000 });
	if (rateLimited) {
		return rateLimited;
	}

	let body: RegisterRequest;
	try {
		body = (await request.json()) as RegisterRequest;
	} catch {
		return errorDeCuenta("INVALID_JSON", 400);
	}

	const { email, password, firstName, lastName, channel, redirectUrl, rut, razonSocial } = body;

	if (!email || !password) {
		return errorDeCuenta("REQUIRED", 400);
	}

	// En un canal de empresa la cuenta nace con su empresa: sin RUT y razón
	// social no hay compra posible, y es mejor detenerlo antes de crear la cuenta
	// que dejar un usuario que no puede comprar. El canal lo valida el servidor;
	// el formulario puede estar desactualizado o ser otro cliente.
	const canalB2B = Boolean(channel) && esCanalB2B(channel);
	const datosEmpresa = empresaDelRegistro(canalB2B, rut, razonSocial);
	if (!datosEmpresa.ok) {
		return errorDeCuenta("EMPRESA_REQUERIDA", 400);
	}

	// Confirmation emails embed this URL — only this deployment's surfaces are allowed.
	if (redirectUrl && !isAllowedRedirectUrl(redirectUrl)) {
		console.warn(
			"Received an invalid redirection URL for password reset. " +
				"Make sure to configure NEXT_PUBLIC_STOREFRONT_URL, " +
				"see https://github.com/saleor/saleor-docs/blob/-/docs/configuration/allowed-origins.md",
			{ redirectUrl },
		);
		return errorDeCuenta("INVALID", 400, "No pudimos crear la cuenta desde esta página. Intenta de nuevo.");
	}

	const result = await executeRawGraphQL<AccountRegisterResult>({
		query: REGISTER_MUTATION,
		variables: {
			input: {
				email,
				password,
				firstName: firstName || "",
				lastName: lastName || "",
				channel,
				redirectUrl,
			},
		},
	});

	// Network or GraphQL error. El detalle se queda en el log: puede traer la
	// respuesta cruda de Saleor.
	if (!result.ok) {
		console.error("Registration error:", result.error.type, result.error.statusCode ?? "");
		return result.error.type === "network"
			? errorDeCuenta("NETWORK", 503, "No pudimos conectar con la tienda. Intenta de nuevo en unos minutos.")
			: errorDeCuenta(result.error.type.toUpperCase(), 400);
	}

	const accountRegister = result.data.accountRegister;

	// Errores de validación de Saleor: el código y el campo sirven al formulario;
	// el `message` de Saleor viene en inglés y se reemplaza por el nuestro.
	if (accountRegister?.errors?.length) {
		return NextResponse.json(
			{
				errors: accountRegister.errors.map((e) => ({
					field: e.field ?? null,
					code: e.code ?? null,
					message: mensajeDeCuenta(e.code),
				})),
			},
			{ status: 400 },
		);
	}

	// Alta de la empresa. En retail `datosEmpresa.empresa` es null y no se
	// registra nada —ni se llama a `tokenCreate`— aunque el cuerpo traiga RUT.
	const empresa = datosEmpresa.empresa
		? await registrarEmpresaDeCuentaNueva(email, password, {
				...datosEmpresa.empresa,
				giro: body.giro,
				telefono: body.telefono,
			})
		: undefined;

	return NextResponse.json({
		user: accountRegister?.user,
		empresa,
		message: "Cuenta creada. Revisa tu correo para confirmarla.",
	});
}
