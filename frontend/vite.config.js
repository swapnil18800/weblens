import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
var BACKEND = "http://127.0.0.1:8765";
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5174,
        strictPort: true,
        proxy: {
            "/api": { target: BACKEND, changeOrigin: true },
        },
    },
    build: {
        outDir: "dist",
        sourcemap: false,
    },
});
