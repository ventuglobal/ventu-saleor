import { NextRequest, NextResponse } from "next/server";
import { rejectIfRateLimited } from "@/lib/auth/auth-rate-limit";
import { isAllowedRedirectUrl } from "@/lib/auth/validate-redirect-url";
import { executeRawGraphQL, asValidationError, getUserMessage } from "@/lib/graphql";
import { registrarEmpresa } from "@/lib/b2b/company";

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

interface RegisterRequest {
	email: string;
	password: string;
	firstName?: string;
	lastName?: string;
	channel: string;
	redirectUrl: string;
	/** Alta de empresa en el mismo paso: quien compra al por mayor compra con RUT. */
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

export async function POST(request: NextRequest) {
	const rateLimited = rejectIfRateLimited(request, "register", { limit: 5, windowMs: 60 * 60 * 1000 });
	if (rateLimited) {
		return rateLimited;
	}

	let body: RegisterRequest;
	try {
		body = (await request.json()) as RegisterRequest;
	} catch {
		return NextResponse.json(
			{ errors: [{ message: "Invalid request body", code: "INVALID_JSON" }] },
			{ status: 400 },
		);
	}

	const { email, password, firstName, lastName, channel, redirectUrl, rut, razonSocial } = body;

	if (!email || !password) {
		return NextResponse.json(
			{ errors: [{ message: "Email and password are required", code: "REQUIRED" }] },
			{ status: 400 },
		);
	}

	// Confirmation emails embed this URL — only this deployment's surfaces are allowed.
	if (redirectUrl && !isAllowedRedirectUrl(redirectUrl)) {
		console.warn(
			"Received an invalid redirection URL for password reset. " +
				"Make sure to configure NEXT_PUBLIC_STOREFRONT_URL, " +
				"see https://github.com/saleor/saleor-docs/blob/-/docs/configuration/allowed-origins.md",
			{ redirectUrl },
		);
		return NextResponse.json(
			{
				errors: [{ message: "Invalid redirect URL. See server logs for more information.", code: "INVALID" }],
			},
			{ status: 400 },
		);
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

	// Network or GraphQL error
	if (!result.ok) {
		console.error("Registration error:", result.error.type);
		return NextResponse.json(
			{ errors: [{ message: getUserMessage(result.error), code: result.error.type.toUpperCase() }] },
			{ status: result.error.type === "network" ? 503 : 400 },
		);
	}

	const accountRegister = result.data.accountRegister;

	// Saleor validation errors
	if (accountRegister?.errors?.length) {
		const validationResult = asValidationError(accountRegister.errors);
		return NextResponse.json({ errors: validationResult.error.validationErrors }, { status: 400 });
	}

	const user = accountRegister?.user;

	// Alta de la empresa. El id sale de la respuesta de Saleor, no del cuerpo de
	// la petición: aceptarlo del cliente permitiría asociar una empresa a la
	// cuenta de otra persona.
	//
	// Si el alta falla, la cuenta igual quedó creada — deshacerla sería peor: el
	// correo ya está tomado y el cliente no podría reintentar. Se informa y el
	// alta se completa después en /empresa.
	let empresa: { ok: boolean; mensaje?: string } | undefined;
	if (user?.id && rut && razonSocial) {
		const alta = await registrarEmpresa(user.id, {
			rut,
			razonSocial,
			giro: body.giro,
			telefono: body.telefono,
		});
		empresa = alta.ok ? { ok: true } : { ok: false, mensaje: alta.mensaje };
	}

	// Success
	return NextResponse.json({
		user,
		empresa,
		message: "Account created successfully. Please check your email to verify your account.",
	});
}
