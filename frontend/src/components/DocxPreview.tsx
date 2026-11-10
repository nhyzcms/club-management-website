import { useEffect, useRef } from "react";
import { renderAsync } from "docx-preview";

/** 在容器里用 docx-preview 渲染 .docx 原件（保真排版，不转站内富文本）。 */
export default function DocxPreview({ url }: { url: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.innerHTML = "";
    let cancelled = false;
    fetch(url, { credentials: "include" })
      .then((r) => r.blob())
      .then((blob) => {
        if (cancelled || !ref.current) return;
        return renderAsync(blob, ref.current, undefined, { inWrapper: true, className: "docx-preview" });
      })
      .catch(() => {
        if (ref.current) ref.current.textContent = "文档预览失败，请下载原件查看。";
      });
    return () => { cancelled = true; };
  }, [url]);

  return <div ref={ref} className="docx-host" />;
}
