import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时前端跑在 5173，请求 /api 自动转发到后端 8000，避免跨域。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
