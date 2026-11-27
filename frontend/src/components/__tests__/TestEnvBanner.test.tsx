import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import TestEnvBanner from "../TestEnvBanner";

describe("TestEnvBanner（test 环境提示）", () => {
  it("生产环境不渲染", () => {
    const { container } = render(<TestEnvBanner environment="production" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("环境未知时不渲染（避免正式站误报）", () => {
    const { container } = render(<TestEnvBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("test 环境显示提示和返回生产链接", () => {
    render(<TestEnvBanner environment="test" />);

    expect(screen.getByRole("status")).toHaveTextContent("测试环境");
    expect(screen.getByRole("link", { name: /返回生产/ })).toHaveAttribute(
      "href",
      "https://8.153.145.175/",
    );
  });

  it("embed 模式不渲染", () => {
    const { container } = render(<TestEnvBanner environment="test" hidden />);
    expect(container).toBeEmptyDOMElement();
  });
});
