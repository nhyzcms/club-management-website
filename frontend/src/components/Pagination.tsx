import type { CSSProperties } from "react";

/**
 * 数字页码器（与新闻列表页原有样式/交互一致）。
 * totalPages <= 1 时不渲染。
 */
export default function Pagination({
  page,
  totalPages,
  onChange,
  style,
}: {
  page: number;
  totalPages: number;
  onChange: (p: number) => void;
  style?: CSSProperties;
}) {
  if (totalPages <= 1) return null;

  // 分页按钮：1 … (page-1,page,page+1) … totalPages
  const entries = (): (number | "ellipsis")[] => {
    const nums = new Set<number>([1, totalPages, page, page - 1, page + 1]);
    const sorted = [...nums].filter((n) => n >= 1 && n <= totalPages).sort((a, b) => a - b);
    const out: (number | "ellipsis")[] = [];
    let prev = 0;
    for (const n of sorted) {
      if (prev && n - prev > 1) out.push("ellipsis");
      out.push(n);
      prev = n;
    }
    return out;
  };

  return (
    <nav className="pager" aria-label="分页" style={{ marginTop: "var(--s-10)", ...style }}>
      <button aria-label="上一页" disabled={page <= 1} onClick={() => onChange(Math.max(1, page - 1))}>
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M11 6l-6 6 6 6" /></svg>
      </button>
      {entries().map((b, i) =>
        b === "ellipsis" ? (
          <span key={"e" + i} className="ellipsis">…</span>
        ) : (
          <button key={b} aria-current={b === page ? "page" : undefined} onClick={() => onChange(b)}>{b}</button>
        )
      )}
      <button aria-label="下一页" disabled={page >= totalPages} onClick={() => onChange(Math.min(totalPages, page + 1))}>
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
      </button>
    </nav>
  );
}
