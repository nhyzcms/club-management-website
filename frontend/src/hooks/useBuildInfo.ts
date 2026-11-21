// 版本信息的单例读取：页脚、更新弹窗、人工点开「更新日志」共用一次请求。
//
// 用了模块级 Promise 而不是每个组件各 fetch 一次：这个数据在整页生命周期里不会变，
// 而页脚在每一页都渲染。失败不重试、不抛给 UI —— 版本号显示不出来不该让页面报错。

import { useEffect, useState } from "react";
import { versionApi, type BuildInfo, type ChangelogEntry } from "../api/version";

let buildInfoPromise: Promise<BuildInfo | null> | null = null;
let changelogPromise: Promise<ChangelogEntry | null> | null = null;

export function loadBuildInfo(): Promise<BuildInfo | null> {
  if (!buildInfoPromise) {
    buildInfoPromise = versionApi.get().catch(() => {
      buildInfoPromise = null; // 下次挂载还能再试（刚部署完的瞬间可能 502）
      return null;
    });
  }
  return buildInfoPromise;
}

export function loadChangelog(): Promise<ChangelogEntry | null> {
  if (!changelogPromise) {
    changelogPromise = versionApi.changelog().catch(() => {
      changelogPromise = null;
      return null;
    });
  }
  return changelogPromise;
}

/** 测试用：清掉缓存，避免用例之间互相污染。 */
export function resetVersionCache() {
  buildInfoPromise = null;
  changelogPromise = null;
}

export function useBuildInfo(): BuildInfo | null {
  const [info, setInfo] = useState<BuildInfo | null>(null);
  useEffect(() => {
    let alive = true;
    loadBuildInfo().then((v) => {
      if (alive) setInfo(v);
    });
    return () => {
      alive = false;
    };
  }, []);
  return info;
}

/** 页脚展示用：release 只显示版本号，dev 带上通道标记。 */
export function formatVersion(info: BuildInfo | null): string {
  if (!info) return "";
  if (info.channel === "release") return `v${info.version}`;
  return `v${info.version}`;
}

/** 悬停提示：把「哪个提交、什么时候构建的」摊开，省得再去问运维。 */
export function versionTooltip(info: BuildInfo | null): string {
  if (!info) return "";
  const parts = [info.channel === "release" ? "发布版本" : "开发版本"];
  if (info.commit_short) parts.push(`提交 ${info.commit_short}`);
  if (info.built_at) parts.push(`构建于 ${info.built_at}`);
  if (info.source !== "build_info.json") parts.push("版本来自本地源码");
  return parts.join(" · ");
}
