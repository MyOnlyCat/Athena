import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiTarget = process.env.ATHENA_MASTER_API_TARGET ?? "http://127.0.0.1:8001";
// @vitejs/plugin-react injects this fixed React Refresh preamble in development.
// Pinning its exact hash keeps inline scripts closed without breaking local rendering.
const reactRefreshPreambleHash =
  "'sha256-Z2/iFzh9VMlVkEOar1f/oSHWwQk3ve1qk/C2WdsC4Xk='";
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' ${reactRefreshPreambleHash}`,
  "script-src-attr 'none'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  "connect-src 'self' ws://127.0.0.1:* ws://localhost:*",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'"
].join("; ");
const securityHeaders = { "Content-Security-Policy": contentSecurityPolicy };

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          "react-vendor": ["react", "react-dom", "react-router-dom"],
          "antd-vendor": ["antd", "@ant-design/icons"],
          "query-vendor": ["@tanstack/react-query", "axios"]
        }
      }
    }
  },
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    headers: securityHeaders,
    proxy: {
      "/api": apiTarget
    }
  },
  preview: {
    headers: securityHeaders
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./tests/setup.ts",
    css: true
  }
});
