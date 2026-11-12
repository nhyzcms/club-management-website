import { describe, expect, it } from "vitest";
import {
  CENTER_CROP_SCALE,
  DECODE_MAX_SIDE,
  buildFocusConstraints,
  buildVideoConstraints,
  centerCropRect,
  containRect,
  mapTapToVideoFraction,
  normalizeCode,
  pickDecodeSize,
  pointOfInterestConstraints,
  readZoomRange,
} from "../utils/barcodeCamera";

/**
 * 摄像头扫码的约束/几何（2026-11-12 修「不对焦 + 画面被自动放大」）。
 * 这些是纯计算，真正的取景行为靠真机验证，这里锁住口径。
 */
describe("buildVideoConstraints", () => {
  it("要后摄、要高分辨率（对焦与解码都需要像素密度）", () => {
    const c = buildVideoConstraints();
    expect(c.facingMode).toEqual({ ideal: "environment" });
    expect(c.width).toEqual({ ideal: 1920 });
    expect(c.height).toEqual({ ideal: 1080 });
  });
});

describe("readZoomRange", () => {
  it("读得到范围就给范围，缺 step 时给默认步长", () => {
    expect(readZoomRange({ zoom: { min: 1, max: 4 } })).toEqual({ min: 1, max: 4, step: 0.1 });
  });
  it("没有变焦能力 / 范围不合法 → null", () => {
    expect(readZoomRange({})).toBeNull();
    expect(readZoomRange(null)).toBeNull();
    expect(readZoomRange({ zoom: { min: 2, max: 2 } })).toBeNull();
    expect(readZoomRange({ zoom: { min: 3, max: 1 } })).toBeNull();
  });
});

describe("buildFocusConstraints", () => {
  it("支持连续对焦就开连续对焦，并把变焦归位到最小（不自动放大）", () => {
    expect(
      buildFocusConstraints({ focusMode: ["manual", "continuous"], zoom: { min: 1, max: 5, step: 0.1 } }),
    ).toEqual([{ focusMode: "continuous", zoom: 1 }]);
  });
  it("顺带开连续曝光", () => {
    expect(buildFocusConstraints({ exposureMode: ["continuous"] })).toEqual([{ exposureMode: "continuous" }]);
  });
  it("机型不支持任何一项就不下发约束（否则会被整条拒绝）", () => {
    expect(buildFocusConstraints({ focusMode: ["manual"], zoom: { min: 1, max: 1 } })).toEqual([]);
    expect(buildFocusConstraints(null)).toEqual([]);
  });
});

describe("pointOfInterestConstraints", () => {
  it("支持点按对焦时给出归一化坐标 + 单次对焦", () => {
    expect(
      pointOfInterestConstraints({ pointsOfInterest: true, focusMode: ["single-shot", "continuous"] }, 0.25, 0.6),
    ).toEqual([{ pointsOfInterest: [{ x: 0.25, y: 0.6 }], focusMode: "single-shot" }]);
  });
  it("坐标越界要夹回 0–1", () => {
    expect(pointOfInterestConstraints({ pointsOfInterest: true }, -1, 2)).toEqual([
      { pointsOfInterest: [{ x: 0, y: 1 }] },
    ]);
  });
  it("不支持点按对焦就什么都不下发", () => {
    expect(pointOfInterestConstraints({ focusMode: ["continuous"] }, 0.5, 0.5)).toEqual([]);
  });
});

describe("pickDecodeSize", () => {
  it("小于上限时原样用，不放大", () => {
    expect(pickDecodeSize(640, 480)).toEqual({ width: 640, height: 480 });
  });
  it("超过上限时等比缩到最长边 1280", () => {
    expect(pickDecodeSize(1920, 1080)).toEqual({ width: DECODE_MAX_SIDE, height: 720 });
    expect(pickDecodeSize(1080, 1920)).toEqual({ width: 720, height: DECODE_MAX_SIDE });
  });
  it("非法的宽高返回 0（调用方直接跳过这一帧）", () => {
    expect(pickDecodeSize(0, 0)).toEqual({ width: 0, height: 0 });
  });
});

describe("centerCropRect", () => {
  it("取画面正中 60%", () => {
    const rect = centerCropRect(1000, 800);
    expect(rect.width).toBe(600);
    expect(rect.height).toBe(480);
    expect(rect.x).toBe(200);
    expect(rect.y).toBe(160);
    expect(CENTER_CROP_SCALE).toBe(0.6);
  });
});

describe("containRect / mapTapToVideoFraction", () => {
  it("16:9 画面放进 4:3 框：上下留黑边，画面不裁切", () => {
    const inner = containRect(400, 300, 16 / 9);
    expect(inner.width).toBe(400);
    expect(inner.height).toBe(225);
    expect(inner.y).toBe(37.5);
  });

  it("49:9 竖屏画面放进横向框：左右留黑边", () => {
    const inner = containRect(400, 300, 0.5);
    expect(inner.width).toBe(150);
    expect(inner.x).toBe(125);
  });

  it("宽度比未知时退化成整框", () => {
    expect(containRect(400, 300, null)).toEqual({ x: 0, y: 0, width: 400, height: 300 });
  });

  it("点击位置换算成画面内 0–1 坐标", () => {
    const box = { left: 0, top: 0, width: 400, height: 300 };
    const point = mapTapToVideoFraction(box, 16 / 9, 200, 150);
    expect(point).toEqual({ x: 0.5, y: 0.5 });
  });

  it("点在黑边上不抢对焦点", () => {
    const box = { left: 0, top: 0, width: 400, height: 300 };
    expect(mapTapToVideoFraction(box, 16 / 9, 200, 10)).toBeNull();
  });
});

describe("normalizeCode", () => {
  it("去掉空白与连字符", () => {
    expect(normalizeCode(" 123 4567 ")).toBe("1234567");
    expect(normalizeCode("123-4567")).toBe("1234567");
    expect(normalizeCode(undefined)).toBe("");
  });
});
