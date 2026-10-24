import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      // backend runs separately, same origin keeps xhr and fetch simple
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "node",
  },
});
