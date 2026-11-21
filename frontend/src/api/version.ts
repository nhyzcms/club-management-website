// 版本与发行说明：让页脚能说出「现在跑的是哪一版」。
//
// 数据由 CI 在构建镜像前写进 build_info.json / changelog.json，运行时由
// /version/ 与 /changelog/ 暴露。前端不猜版本号，也不读构建时间。

import { createRequest } from "./shared";

const request = createRequest("");

export interface BuildInfo {
  version: string;
  base_version: string;
  /** release = 打过 tag 的发布版本；dev = 分支构建 */
  channel: string;
  tag: string | null;
  commit: string;
  commit_short: string;
  commits_since_tag: number | null;
  built_at: string;
  built_by: string;
  source: string;
}

export interface ChangelogSection {
  title: string;
  items: string[];
}

export interface ChangelogEntry {
  /** 人写的一句话摘要（CHANGELOG 该节的引用块）。自动生成的部分是 commit 原文，
   *  只有这句是「和你有什么关系」。 */
  summary?: string | null;
  version: string | null;
  released: string | null;
  sections: ChangelogSection[];
}

export const versionApi = {
  get: () => request("/version/") as Promise<BuildInfo>,
  changelog: () => request("/changelog/") as Promise<ChangelogEntry>,
};
