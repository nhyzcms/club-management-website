/**
 * 扫码结果 → 社员查询入口 的纯文本解析。
 *
 * 工牌上印了两种码（见 accounts/member_qr.py / accounts/member_barcode.py），
 * 扫到的东西完全不是一个形状：
 * - **二维码**：带 HMAC 签名的校验页 URL `<FRONTEND_URL>/#/v/<8位识别码>?s=<签名>`，
 *   走 `/member/check/`（签名挡住猜码遍历，不扣查询额度）；
 * - **条形码**（Code128）：只承载裸识别码（8 位数字）。条形码不是链接载体——微信扫
 *   Code128 只会显示数字，所以它只能回退到 `/member/lookup/`（扣额度，见 member_lookup.py）。
 *
 * 这里只做纯函数解析、不发请求：扫码器输出常有前后空白 / BOM / 大写签名，
 * 单测可以直接钉死这些边角。
 */

export type ScanPayload =
  | { kind: "verify"; code: string; sig: string; raw: string }
  | { kind: "code"; code: string; raw: string }
  | { kind: "unknown"; raw: string };

/** 社员识别码 v2：8 位数字（[入学年2][首次入社届2][姓名GBK序2][MOD97-10 校验2]）。 */
const CODE_RE = /^\d{8}$/;
/** 校验签名：HMAC-SHA256 前 16 位十六进制（accounts/member_codes.SIG_HEX_LEN）。 */
const SIG_RE = /^[0-9a-f]{16}$/i;

/**
 * 从一个 URL 里取出 (识别码, 签名)。
 *
 * - HashRouter 落点：`https://host/#/v/26010201?s=0123456789abcdef`；
 * - 兼容直接打接口的写法：`.../v/26010201?s=...`、`?c=26010201&s=...`。
 * 取不到识别码就返回 null（交给后面的兜底分支）。
 */
function fromUrl(text: string): { code: string; sig: string } | null {
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;

  // 签名可能出现在 hash 的查询串里（#/v/<码>?s=...），也可能在真查询串里
  const hash = url.hash.replace(/^#/, "");
  const [hashPath, hashQuery = ""] = hash.split("?");
  const hashParams = new URLSearchParams(hashQuery);

  const code =
    hashPath.match(/^\/v\/(\d{8})(?:\/|$)/)?.[1] ||
    hashPath.match(/^\/(\d{8})$/)?.[1] ||
    url.pathname.match(/(?:^|\/)v\/(\d{8})(?:\/|$)/)?.[1] ||
    url.searchParams.get("c") ||
    "";
  if (!CODE_RE.test(code)) return null;

  const sig = (hashParams.get("s") || url.searchParams.get("s") || "").trim();
  return { code, sig: SIG_RE.test(sig) ? sig.toLowerCase() : "" };
}

/**
 * 解析扫码器返回的原始文本。
 *
 * 返回值三种，调用方据此选接口：
 * - `verify` → `/member/check/`（签名齐全）；
 * - `code`   → `/member/lookup/`（只有裸识别码，或链接里缺签名）；
 * - `unknown`→ 提示「不是本站工牌」。
 */
export function parseScannedText(raw: string): ScanPayload {
  const text = (raw || "").replace(/^\uFEFF/, "").trim();
  if (!text) return { kind: "unknown", raw: text };

  const parsed = fromUrl(text);
  if (parsed) {
    return parsed.sig
      ? { kind: "verify", code: parsed.code, sig: parsed.sig, raw: text }
      : { kind: "code", code: parsed.code, raw: text };
  }

  if (CODE_RE.test(text)) return { kind: "code", code: text, raw: text };

  return { kind: "unknown", raw: text };
}
