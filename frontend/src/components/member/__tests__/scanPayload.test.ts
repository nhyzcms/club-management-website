import { describe, expect, it } from "vitest";

import { parseScannedText } from "../scanPayload";

const SIG = "0123456789abcdef"; // HMAC-SHA256 前 16 位（accounts/member_codes.SIG_HEX_LEN）

describe("parseScannedText（扫码结果解析）", () => {
  it("条形码的裸识别码 → 走查询接口", () => {
    expect(parseScannedText("26010201")).toEqual({ kind: "code", code: "26010201", raw: "26010201" });
  });

  it("二维码的签名链接（HashRouter 落点）→ 走校验接口", () => {
    const text = `https://8.153.145.175/#/v/26010201?s=${SIG}`;
    expect(parseScannedText(text)).toEqual({ kind: "verify", code: "26010201", sig: SIG, raw: text });
  });

  it("兼容接口式链接与兼容大写签名", () => {
    const text = `https://8.153.145.175/v/26010201?s=${SIG.toUpperCase()}`;
    expect(parseScannedText(text)).toEqual({ kind: "verify", code: "26010201", sig: SIG, raw: text });
    const api = `https://8.153.145.175/?c=26010201&s=${SIG}`;
    expect(parseScannedText(api)).toEqual({ kind: "verify", code: "26010201", sig: SIG, raw: api });
  });

  it("链接里缺签名 → 退化成裸识别码查询", () => {
    const text = "https://8.153.145.175/#/v/26010201";
    expect(parseScannedText(text)).toEqual({ kind: "code", code: "26010201", raw: text });
  });

  it("签名格式不对（长度不是 16 位十六进制）按缺签名处理", () => {
    const text = "https://8.153.145.175/#/v/26010201?s=not-a-signature";
    expect(parseScannedText(text)).toMatchObject({ kind: "code", code: "26010201" });
  });

  it("容忍前后空白与 BOM（部分扫码器会带）", () => {
    expect(parseScannedText("\uFEFF 26010201 \n")).toMatchObject({ kind: "code", code: "26010201" });
  });

  it("不是本站工牌的内容 → unknown", () => {
    expect(parseScannedText("https://example.com/hello")).toMatchObject({ kind: "unknown" });
    expect(parseScannedText("2601020")).toMatchObject({ kind: "unknown" }); // 7 位
    expect(parseScannedText("")).toMatchObject({ kind: "unknown" });
  });
});
