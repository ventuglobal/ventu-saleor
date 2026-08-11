import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
	test: {
		globals: true,
		environment: "node",
		setupFiles: ["./vitest.setup.ts"],
		include: ["src/**/*.test.ts", "scripts/**/*.test.mjs"],
		exclude: ["src/**/*.export-harness.test.ts"],
	},
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "./src"),
			// `server-only` lanza al importarse. Es lo correcto en un bundle de
			// cliente, pero deja sin pruebas a cualquier módulo que lleve la marca.
			// Se sustituye por un stub vacío, que es lo que el módulo hace en el
			// servidor.
			"server-only": path.resolve(__dirname, "./src/test/server-only-stub.ts"),
		},
	},
});
