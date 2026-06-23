import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/auth": "http://127.0.0.1:8000",
      "/applicants": "http://127.0.0.1:8000",
      "/applications": "http://127.0.0.1:8000",
      "/staff": "http://127.0.0.1:8000",
      "/analytics": "http://127.0.0.1:8000",
      "/reports": "http://127.0.0.1:8000"
    }
  }
});
