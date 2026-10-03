import { type AddressFragment } from "@/checkout/graphql";
import { type BillingAddressData } from "@/checkout/components/payment";

/** Mismos datos de facturación que consume el flujo de Stripe; Webpay los reusa. */
export type WebpayBillingContext = {
	billingData: BillingAddressData;
	sameAsBilling: boolean;
	hasShippingAddress: boolean;
	shippingAddress: AddressFragment | null | undefined;
	userAddresses: ReadonlyArray<AddressFragment> | undefined;
	authenticated: boolean;
};
