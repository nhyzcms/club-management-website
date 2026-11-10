import { useEffect } from "react";

/**
 * 全屏看图（lightbox）：点击背景 / Esc 关闭。
 *
 * 用真实 <img> 渲染（不做 touch-callout 拦截）：移动端长按可直接
 * 「保存图片」；桌面端右键另存。max-height 88vh 留出提示文字空间。
 */
export default function ImageLightbox({ url, alt, onClose }: { url: string; alt?: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="image-lightbox" role="dialog" aria-modal="true" aria-label="查看大图" onClick={onClose}>
      <img src={url} alt={alt || ""} onClick={(e) => e.stopPropagation()} />
      <span className="image-lightbox-hint">点击空白处关闭 · 长按图片保存</span>
    </div>
  );
}
