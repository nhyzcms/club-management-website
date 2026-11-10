import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// 未启用 globals：每个用例后手动卸载组件树
afterEach(() => {
  cleanup();
});
