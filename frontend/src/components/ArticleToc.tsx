import { useMemo } from "react";

export interface TocHeading {
  id: string;
  level: 2 | 3;
  text: string;
}

/** 从正文 HTML 抽出 h2/h3；不足两个标题时 TOC 应隐藏。 */
export function headingsFromHtml(html: string): TocHeading[] {
  if (!html) return [];
  const doc = new DOMParser().parseFromString(html, "text/html");
  const nodes = Array.from(doc.querySelectorAll("h2, h3"));
  return nodes.map((el, i) => ({
    id: el.id || `toc-h-${i}`,
    level: (el.tagName === "H3" ? 3 : 2) as 2 | 3,
    text: (el.textContent || "").trim(),
  })).filter((h) => h.text);
}

/** 给正文标题补上稳定 id，便于目录跳转（新闻等 dangerouslySetInnerHTML 路径）。 */
export function htmlWithHeadingIds(html: string): { html: string; headings: TocHeading[] } {
  const headings = headingsFromHtml(html);
  if (headings.length < 2) return { html, headings };
  const doc = new DOMParser().parseFromString(html, "text/html");
  Array.from(doc.querySelectorAll("h2, h3")).forEach((el, i) => {
    if (headings[i]) el.id = headings[i].id;
  });
  return { html: doc.body.innerHTML, headings };
}

function scrollToHeading(heading: TocHeading, root?: HTMLElement | null) {
  const scoped = root || document;
  const byId = document.getElementById(heading.id);
  if (byId) {
    byId.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  const nodes = scoped.querySelectorAll("h2, h3");
  for (const el of Array.from(nodes)) {
    if ((el.textContent || "").trim() === heading.text) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
  }
}

export default function ArticleToc({
  html,
  root,
}: {
  html: string;
  root?: HTMLElement | null;
}) {
  const headings = useMemo(() => headingsFromHtml(html), [html]);
  if (headings.length < 2) return null;
  return (
    <nav className="article-toc" aria-label="目录">
      <h4 className="article-toc-title">目录</h4>
      <ol>
        {headings.map((h) => (
          <li key={h.id} className={h.level === 3 ? "is-h3" : "is-h2"}>
            <a
              href={`#${h.id}`}
              onClick={(e) => {
                e.preventDefault();
                scrollToHeading(h, root);
              }}
            >
              {h.text}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
