import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    cssCodeSplit: false,
    emptyOutDir: false,
    outDir: "static/dist/copilotkit",
    rollupOptions: {
      input: "static/src/copilotkit/main.jsx",
      output: {
        entryFileNames: "copilotkit-island.js",
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith(".css")) {
            return "copilotkit-island.css";
          }
          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
});
