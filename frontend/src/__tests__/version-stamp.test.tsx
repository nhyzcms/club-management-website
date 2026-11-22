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
  summary: "页面底部现在能看到版本号。",
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

  it("开发版显示「基准版本+第几个提交」，不把 dev 串贴脸上", () => {
    expect(
      formatVersion({
        ...BASE,
        version: "1.0.1-dev.4.gabc1234",
        base_version: "1.0.1",
        channel: "dev",
        commits_since_tag: 4,
      }),
    ).toBe("v1.0.1+4");
  });

  it("开发版拿不到 tag 距离时退回完整版本号", () => {
    expect(
      formatVersion({
        ...BASE,
        version: "1.0.1-dev.4.gabc1234",
        channel: "dev",
        tag: null,
        commits_since_tag: null,
      }),
    ).toBe("v1.0.1-dev.4.gabc1234");
  });

  it("没有数据时不显示任何字符", () => {
    expect(formatVersion(null)).toBe("");
    expect(versionTooltip(null)).toBe("");
  });

  it("悬停提示带上提交与本地化的构建时间", () => {
    const tip = versionTooltip(BASE);
    expect(tip).toContain("发布版本");
    expect(tip).toContain("335d91e");
    // 给机器看的 UTC 不该原样丢给用户 ISO 串
    expect(tip).not.toContain("T04:31:20Z");
    expect(tip).toMatch(/构建于 \d{4}\/\d{2}\/\d{2} \d{2}:\d{2}/);
  });

  it("开发版的悬停提示交代离 tag 多远和完整构建版本", () => {
    const tip = versionTooltip({
      ...BASE,
      version: "1.1.0-dev.3.g3e698c6",
      channel: "dev",
      tag: "v1.1.0",
      commits_since_tag: 3,
      commit_short: "3e698c6",
    });
    expect(tip).toContain("开发版本");
    expect(tip).toContain("v1.1.0 之后第 3 个提交");
    expect(tip).toContain("1.1.0-dev.3.g3e698c6");
    expect(tip).toContain("3e698c6");
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
    await waitFor(() => expect(changelog).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("dev 构建设有新的发行说明时也要弹（这正是修复的问题）", async () => {
    // 线上永远是 tag 之后的 dev 构建：如果继续按 channel 卡，弹窗从不出现。
    localStorage.setItem(SEEN_VERSION_KEY, "0.9.1");
    mount({ channel: "dev", version: "1.0.1-dev.2.gdeadbee" });
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });

  it("构建版本变了但发行说明没变，不重复弹", async () => {
    // 同一次发版会被切成多个 dev 构建，社员不该每换一个提交就被弹一次。
    localStorage.setItem(SEEN_VERSION_KEY, "1.0.1");
    mount({ channel: "dev", version: "1.0.1-dev.9.gfedcba9" });
    await waitFor(() => expect(changelog).toHaveBeenCalled());
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

  it("没有发行说明时无从记录，也不写脏数据", async () => {
    // 记的是「发行说明版本」；没有说明就没有版本，硬记构建号会让下一版永远判成「见过」。
    mount({}, { version: null, released: null, sections: [] });
    await waitFor(() => expect(changelog).toHaveBeenCalled());
    expect(localStorage.getItem(SEEN_VERSION_KEY)).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("没有发行说明时，「更新日志」点开不该弹空窗", async () => {
    localStorage.setItem(SEEN_VERSION_KEY, "1.0.0");
    mount({}, { version: null, released: null, sections: [] });
    await waitFor(() => expect(changelog).toHaveBeenCalled());
    openChangelog();
    await waitFor(() => expect(changelog).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("页脚「更新日志」事件能重新打开", async () => {
    localStorage.setItem(SEEN_VERSION_KEY, "1.0.1");
    mount();
    await waitFor(() => expect(changelog).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).toBeNull();

    openChangelog();
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(OPEN_CHANGELOG_EVENT).toBe("club:open-changelog");
  });
});

describe("更新说明的「人话摘要」", () => {
  beforeEach(() => {
    localStorage.clear();
    resetVersionCache();
    get.mockReset();
    changelog.mockReset();
  });

  it("摘要显示在条目之前", async () => {
    localStorage.setItem(SEEN_VERSION_KEY, "1.0.0");
    mount();
    await screen.findByRole("dialog");
    const text = document.body.textContent ?? "";
    expect(text).toContain("页面底部现在能看到版本号。");
    // 摘要在第一条 section 标题之前
    expect(text.indexOf("页面底部现在能看到版本号。")).toBeLessThan(text.indexOf("修复"));
  });

  it("没有摘要也能正常显示，不出现空段落", async () => {
    localStorage.setItem(SEEN_VERSION_KEY, "1.0.0");
    mount({}, { ...ENTRY, summary: null });
    await screen.findByRole("dialog");
    expect(document.body.textContent).toContain("修了一处");
  });
});
