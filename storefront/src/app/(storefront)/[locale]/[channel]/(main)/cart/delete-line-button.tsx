"use client";

import { useTranslations } from "next-intl";

import { useTransition } from "react";
import { ariaDisabledClassName } from "@/ui/components/ui/button";
import { cn } from "@/lib/utils";

type Props = {
	deleteLine: () => Promise<void>;
};

export const DeleteLineButton = ({ deleteLine }: Props) => {
	const [isPending, startTransition] = useTransition();
	const t = useTranslations("cart.page");

	return (
		<button
			type="button"
			className={cn(
				"text-sm text-muted-foreground hover:text-foreground",
				ariaDisabledClassName,
				"aria-disabled:opacity-60",
			)}
			onClick={() => {
				if (isPending) return;
				startTransition(() => {
					void deleteLine();
				});
			}}
			aria-disabled={isPending}
		>
			{isPending ? t("removing") : t("remove")}
			<span className="sr-only">{t("srLineFromCart")}</span>
		</button>
	);
};
