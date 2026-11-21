import { useEffect } from "react";
import type { ChangelogEntry } from "../api/version";

/**
 * 「这次更新了什么」弹窗。
 *
 * 自包含 inline 样式，与 NoticeModal / SessionSupersedeModal 同风格（不引新 CSS 依赖）。
 * 关闭途径：底栏按钮 / 点遮罩 / Esc。
 */
export default function ChangelogModal({
  entry,
  onClose,
}: {
  entry: ChangelogEntry;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const subtitle = [entry.version ? `v${entry.version}` : "", entry.released ?? ""]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="更新内容"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg)",
          borderRadius: 10,
          width: 520,
          maxWidth: "100%",
          maxHeight: "80vh",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 12px 40px rgba(0,0,0,0.25)",
        }}
      >
        <div style={{ padding: "20px 24px 12px" }}>
          <h3 style={{ margin: 0, fontSize: 18 }}>这次的更新</h3>
          {subtitle && (
            <p
              className="tnum"
              style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: 13, fontFamily: "var(--font-mono)" }}
            >
              {subtitle}
            </p>
          )}
        </div>

        <div style={{ padding: "0 24px", overflowY: "auto", flex: 1 }}>
          {entry.summary && (
            <p
              style={{
                margin: "4px 0 18px",
                fontSize: 15,
                lineHeight: 1.7,
                color: "var(--fg)",
              }}
            >
              {entry.summary}
            </p>
          )}
          {entry.sections.map((section) => (
            <section key={section.title} style={{ marginBottom: 16 }}>
              <h4
                style={{
                  margin: "0 0 6px",
                  fontSize: 13,
                  letterSpacing: ".02em",
                  color: "var(--brand-600)",
                }}
              >
                {section.title}
              </h4>
              <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7, fontSize: 14 }}>
                {section.items.map((item, i) => (
                  <li key={`${section.title}-${i}`}>{item}</li>
                ))}
              </ul>
            </section>
          ))}
        </div>

        <div style={{ padding: 16, display: "flex", justifyContent: "flex-end" }}>
          <button
            type="button"
            onClick={onClose}
            style={{
              padding: "8px 18px",
              borderRadius: 6,
              border: "none",
              cursor: "pointer",
              background: "var(--brand-600)",
              color: "#fff",
              fontSize: 14,
            }}
          >
            知道了
          </button>
        </div>
      </div>
    </div>
  );
}
