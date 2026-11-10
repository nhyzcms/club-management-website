import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

/**
 * 前端单元 / 组件测试（Vitest + React Testing Library + jsdom）。
 *
 * 运行：cd frontend && npm test（一次性）/ npm run test:watch（监视模式）
 * 与 webpack 构建互不影响：测试文件不被 src/index.tsx 引用，不会进产物。
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
  },
});
