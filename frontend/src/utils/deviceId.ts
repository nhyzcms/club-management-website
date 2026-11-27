const STORAGE_KEY = "device_id";

/**
 * 生成 v4 UUID。
 *
 * `crypto.randomUUID()` 只在**安全上下文**可用（HTTPS / localhost）。test 环境是
 * 公网明文 HTTP，`randomUUID` 为 undefined——旧实现直接调用会抛异常，而
 * `createRequest` 在构造 `X-Device-Id` 时就把异常吞成 network error，导致整站
 * 所有 API 请求都失败（页面能渲染，但版本号、登录态、列表全空）。
 *
 * 非安全上下文下 `crypto.getRandomValues()` 仍可用，用它拼 v4 UUID；
 * 连 crypto 都没有（极老浏览器）才用 Math.random 兜底——这个 ID 只用于访客
 * 问卷去重，不是安全凭据。
 */
export function createDeviceId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  const bytes = new Uint8Array(16);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }

  // RFC 4122 v4：版本位 0100，变体位 10xx。
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** 访客问卷去重用的浏览器侧标识（UUID，落 localStorage）。不是硬件 ID。 */
export function getDeviceId(): string {
  try {
    const existing = localStorage.getItem(STORAGE_KEY);
    if (existing) return existing;
    const id = createDeviceId();
    localStorage.setItem(STORAGE_KEY, id);
    return id;
  } catch {
    // 隐私模式 / 存储被禁用：不落盘，但请求仍要能发出去。
    return createDeviceId();
  }
}
