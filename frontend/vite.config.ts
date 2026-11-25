import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The browser calls "/api/*". Vite forwards it to the FastAPI server and strips the "/api" prefix,
// so "/api/os-layer/status" reaches "GET /os-layer/status" and there is no CORS to configure.
// The same proxy is used by `npm run dev` and `npm run preview`.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.BACKEND_URL || "http://127.0.0.1:8000";
  const proxy = {
    "/api": {
      target: backend,
      changeOrigin: true,
      rewrite: (path: string) => path.replace(/^\/api/, ""),
    },
  };

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
    server: { port: 5173, proxy },
    preview: { port: 4173, proxy },
  };
});
