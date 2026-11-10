/**
 * 从用户粘的 raw embed HTML 里抽出可嵌入的 iframe。
 * 只取第一个 <iframe> 的 src（+ title），丢弃其余属性——含 sandbox / srcdoc / onload：
 * 服务端 sanitize_html 会再洗一遍并统一盖 sandbox（common/rich_text.py），前端解析仅为便利、非安全边界。
 * src 非 https（含 http / 相对 / 无 <iframe>）→ 返回 null，调用方提示。
 */
export function parseIframeEmbed(
  raw: string,
): { src: string; title?: string } | null {
  const text = (raw || "").trim();
  if (!text) return null;
  const doc = new DOMParser().parseFromString(text, "text/html");
  const iframe = doc.querySelector("iframe");
  if (!iframe) return null;
  const src = (iframe.getAttribute("src") || "").trim();
  // 接受 https:// 或协议相对 //host（后者在 https 站点即 https；常见 embed 惯例，如网易云外链播放器）
  if (!/^https:\/\//i.test(src) && !src.startsWith("//")) return null;
  const title = iframe.getAttribute("title") || undefined;
  return title ? { src, title } : { src };
}
