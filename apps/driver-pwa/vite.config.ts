import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { defineConfig } from "vitest/config";

// Cross-origin isolation enables multi-threaded WebAssembly for ONNX Runtime Web.
// "credentialless" keeps cross-origin images and API calls working (CORS still applies).
const isolationHeaders = {
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Embedder-Policy": "credentialless",
};

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png"],
      manifest: {
        name: "VíaSegura IA — Conductor",
        short_name: "VíaSegura",
        description:
          "Detecta baches y obstáculos con la cámara del celular y avisa a otros conductores.",
        lang: "es",
        start_url: "/",
        scope: "/",
        display: "standalone",
        orientation: "any",
        background_color: "#0b1220",
        theme_color: "#0b1220",
        icons: [
          { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "icons/icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // Everything the app needs offline (airplane mode): shell, model, WASM runtime, demo video.
        globPatterns: ["**/*.{js,css,html,svg,png,json,onnx,wasm,mjs,webm}"],
        maximumFileSizeToCacheInBytes: 64 * 1024 * 1024,
        navigateFallback: "/index.html",
        cleanupOutdatedCaches: true,
      },
    }),
  ],
  server: { headers: isolationHeaders, host: true, port: 5173 },
  preview: { headers: isolationHeaders, host: true, port: 4173 },
  worker: { format: "es" },
  optimizeDeps: { exclude: ["onnxruntime-web"] },
  test: { environment: "node", include: ["tests/**/*.test.ts"] },
});
