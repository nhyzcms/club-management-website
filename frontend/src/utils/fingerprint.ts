/**
 * 明信片互寄 · 轻量设备指纹（方案 docs/plans/postcard-exchange.md §8 解释 #4）。
 *
 * 与 ncdid Cookie（DeviceIDMiddleware）双轨并用的「第二轨」：换浏览器 / 清 Cookie
 * 后仍能认出同一设备的历史登记。服务端只存 SHA-256 哈希（views._fingerprint_hash），
 * 不落明文——这里产出的是本机信号的哈希摘要，本身不含个人信息。
 *
 * 契约（serializers._FINGERPRINT_RE）：8~128 位小写 hex；格式不符时后端静默降级
 * 为仅 Cookie 识别，不报错。
 *
 * 稳定性设计：canvas / 屏幕 / UA / 时区 / 语言等信号哈希一次后**落 localStorage**——
 * 显卡驱动更新可能让 canvas 渲染结果变化，持久化保证已登记用户不丢归属。
 */
const STORAGE_KEY = "cobalt:postcard-fp";

/** cyrb53 风格双 32 位哈希 → 16 位 hex（同步、零依赖、碰撞面足够设备识别用）。 */
function hashHex(input: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < input.length; i++) {
    const ch = input.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (h2 >>> 0).toString(16).padStart(8, "0") + (h1 >>> 0).toString(16).padStart(8, "0");
}

/** 采集本机稳定信号。任何一项取不到都跳过——指纹降级但不失败。 */
function collectSignals(): string {
  const parts: string[] = [];
  try {
    // canvas 渲染指纹：同设备同浏览器的抗锯齿/字形光栅结果稳定
    const canvas = document.createElement("canvas");
    canvas.width = 220;
    canvas.height = 40;
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.textBaseline = "top";
      ctx.font = "14px 'Arial'";
      ctx.fillStyle = "#f60";
      ctx.fillRect(0, 0, 220, 20);
      ctx.fillStyle = "#069";
      ctx.fillText("nhyz-media-postcard-fp", 2, 2);
      ctx.fillStyle = "rgba(102, 204, 0, 0.7)";
      ctx.fillText("nhyz-media-postcard-fp", 4, 4);
      parts.push(canvas.toDataURL().slice(-96));
    }
  } catch {
    /* canvas 不可用（隐私模式 / 无头环境）→ 跳过该信号 */
  }
  try {
    const s = window.screen;
    parts.push(`${s.width}x${s.height}x${s.colorDepth}`);
  } catch {
    /* 跳过 */
  }
  parts.push(navigator.userAgent || "");
  try {
    parts.push(Intl.DateTimeFormat().resolvedOptions().timeZone || "");
  } catch {
    /* 跳过 */
  }
  parts.push(navigator.language || "");
  return parts.join("|");
}

/** 取本机指纹（hex）。首次计算后持久化；localStorage 不可用时每次重算（信号相同 → 结果相同）。 */
export function getPostcardFingerprint(): string {
  let cached = "";
  try {
    cached = localStorage.getItem(STORAGE_KEY) || "";
  } catch {
    /* 隐私模式：跳过缓存 */
  }
  if (/^[0-9a-f]{8,128}$/.test(cached)) return cached;
  const fp = hashHex(collectSignals());
  try {
    localStorage.setItem(STORAGE_KEY, fp);
  } catch {
    /* 写不进就算了 */
  }
  return fp;
}
