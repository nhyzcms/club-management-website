import { describe, expect, it } from "vitest";
import {
  APP_COPYRIGHT,
  APP_LICENSE,
  APP_NAME,
  APP_SOURCE,
  APP_WEBSITE,
  appVersionLabel,
} from "../aboutApp";

const MOBILE_UA =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
  + "Chrome/125.0.0.0 Mobile Safari/537.36";
const APP_UA = MOBILE_UA + " NhyzClubApp/0.2.0 (Android; 2) NhyzClubShell/0.2.0 (native; 2)";

describe("appVersionLabel（关于 APP 页的版本号）", () => {
  it("壳 UA：版本名 + 版本码", () => {
    expect(appVersionLabel(APP_UA)).toBe("0.2.0（版本码 2）");
  });

  it("版本码两位数不会被截断（0.10.0 / 10）", () => {
    expect(appVersionLabel(`${MOBILE_UA} NhyzClubApp/0.10.0 (Android; 10)`)).toBe(
      "0.10.0（版本码 10）",
    );
  });

  it("解析出版本名但缺版本码时只显示版本名，不编数字", () => {
    expect(appVersionLabel(`${MOBILE_UA} NhyzClubApp/0.2.0`)).toBe("0.2.0");
  });

  it("非壳 UA（手机浏览器 / 桌面）返回 null —— 页面对它们不可达", () => {
    expect(appVersionLabel(MOBILE_UA)).toBeNull();
    expect(appVersionLabel("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Gecko/20100101")).toBeNull();
    expect(appVersionLabel("")).toBeNull();
  });
});

describe("关于 APP 页的静态信息", () => {
  it("名称 / 协议 / 官网 / 开源地址都指向约定值", () => {
    expect(APP_NAME).toBe("南汇一中传媒社");
    expect(APP_LICENSE).toBe("BSD 3-Clause License");
    expect(APP_WEBSITE).toBe("https://nhyzcms.github.io");
    expect(APP_SOURCE).toBe("https://github.com/nhyzcms/app");
    expect(APP_COPYRIGHT).toBe("南汇一中传媒社信息组");
  });
});
