import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ThemeToggle from "../ThemeToggle";
import { STORAGE_KEY } from "../../theme";

describe("ThemeToggle（昼夜开关）", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("渲染为 switch：默认浅色、aria-checked=false", () => {
    render(<ThemeToggle />);

    const sw = screen.getByRole("switch", { name: "深色模式" });
    expect(sw).toHaveAttribute("aria-checked", "false");
  });

  it("点击切到深色：aria-checked / html[data-theme] / localStorage 同步", () => {
    render(<ThemeToggle />);

    fireEvent.click(screen.getByRole("switch", { name: "深色模式" }));

    expect(screen.getByRole("switch", { name: "深色模式" })).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("dark");
  });

  it("再点回到浅色", () => {
    render(<ThemeToggle />);

    const sw = () => screen.getByRole("switch", { name: "深色模式" });
    fireEvent.click(sw());
    fireEvent.click(sw());

    expect(sw()).toHaveAttribute("aria-checked", "false");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("light");
  });

  it("system 偏好看跟随结果，点击后转为显式选择", () => {
    localStorage.setItem(STORAGE_KEY, "system");
    render(<ThemeToggle />);

    fireEvent.click(screen.getByRole("switch", { name: "深色模式" }));

    expect(localStorage.getItem(STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
