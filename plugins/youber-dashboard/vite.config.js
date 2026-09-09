import { defineConfig } from "vite";

// La UI se sirve bajo el prefijo del plugin (/youber-dashboard) desde el
// iframe del tab; base = prefijo para que los assets se resuelvan ahí.
export default defineConfig({
  base: "/youber-dashboard/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
  },
  server: {
    port: 5199,
    strictPort: false,
  },
});
