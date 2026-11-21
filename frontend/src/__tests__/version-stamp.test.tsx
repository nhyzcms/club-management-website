import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

// 版本数据来自后端；这里直接替身，不跑真实 fetch。
const get = vi.fn();
const changelog = vi.fn();
vi.mock("../api/version", () => ({
  versionApi: {
    get: () => get(),
    changelog: () => changelog(),
  },
}));

import ChangelogHost, { OPEN_CHANGELOG_EVENT, SEEN_VERSION_KEY, openChangelog } from "../components/ChangelogHost";
import { formatVersion, resetVersionCache, versionTooltip } from "../hooks/useBuildInfo";
import type { BuildInfo, ChangelogEntry } from "../api/version";

const BASE: BuildInfo = {
  version: "1.0.1",
  base_version: "1.0.1",
  channel: "release",
  tag: "v1.0.1",
  commit: "335d91e55189fcb4ecb2cf5c39c333cd21724602",
  commit_short: "335d91e",
  commits_since_tag: 0,
  built_at: "2026-11-21T04:31:20Z",
  built_by: "github-actions",
  source: "build_info.json",
};

const ENTRY: ChangelogEntry = {
  version: "1.0.1",
  released: "2026-11-21",
  sections: [{ title: "修复", items: ["修了一处"] }],
};

function mount(info: Partial<BuildInfo> = {}, entry: ChangelogEntry = ENTRY) {
  get.mockResolvedValue({ ...BASE, ...info });
  changelog.mockResolvedValue(entry);
  return render(<ChangelogHost />);
}

describe("版本号格式化", () => {
  it("发布版显示 v 前缀", () => {
    expect(formatVersion(BASE)).toBe("v1.0.1");
  });

  it("开发版把 dev 后缀原样带出来", () => {
    expect(formatVersion({ ...BASE, version: "1.0.1-dev.4.gabc1234", channel: "dev" }))
      .toBe("v1.0.1-dev.4.gabc1234");
  });

  it("没有数据时不显示任何字符", () => {
    expect(formatVersion(null)).toBe("");
    expect(versionTooltip(null)).toBe("");
  });

  it("悬停提示带上提交与构建时间", () => {
    const tip = versionTooltip(BASE);
    expect(tip).toContain("发布版本");
    expect(tip).toContain("335d91e");
    expect(tip).toContain("2026-11-21T04:31:20Z");
  });
});

describe("ChangelogHost 弹窗时机", () => {
  beforeEach(() => {
    localStorage.clear();
    resetVersionCache();
    get.mockReset();
    changelog.mockReset();
  });

  it("首次访问只记下版本，不弹", async () => {
    mount();
    await waitFor(() => expect(localStorage.getItem(SEEN_VERSION_KEY)).toBe("1.0.1"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("见过旧版本 → 弹窗", async () => {
    localStorage.setItem(SEEN_VERSION_KEY, "1.0.0");
    mount();
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(screen.getByText("修了一处")).toBeTruthy();
  });

  it("同一版本不重复弹", async () => {
    localStorage.setItem(SEEN_VERSION_KEY, "1.0.1");
    mount();
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("开发版不打扰", async () => {
    localStorage.setItem(SEEN_VERSION_KEY, "0.9.0");
    mount({ channel: "dev", version: "1.0.1-dev.2.gdeadbee" });
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("没有发行说明时即使版本变了也不弹空窗", async () => {
    localStorage.setItem(SEEN_VERSION_KEY, "0.9.0");
    mount({}, { version: null, released: null, sections: [] });
    await waitFor(() => expect(changelog).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("关掉之后记住这一版", async () => {
    localStorage.setItem(SEEN_VERSION_KEY, "1.0.0");
    mount();
    const button = await screen.findByRole("button", { name: "知道了" });
    fireEvent.click(button);
    await waitFor(() => expect(localStorage.getItem(SEEN_VERSION_KEY)).toBe("1.0.1"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("页脚「更新日志」事件能重新打开", async () => {
    localStorage.setItem(SEEN_VERSION_KEY, "1.0.1");
    mount();
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).toBeNull();

    openChangelog();
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(OPEN_CHANGELOG_EVENT).toBe("club:open-changelog");
  });
});
