import { useEffect, type ReactNode } from "react";

/**
 * 通用二次确认弹窗（危险操作最后一道闸）。
 *
 * 与 NoticeModal 同风格（自包含 inline 样式，不引新 CSS 依赖），区别是**两个出口**：
 * 「取消」= onCancel，「确认」= onConfirm。Esc / 点遮罩都算取消——危险操作不能靠误触确认。
 * 表单校验仍由调用方负责：本组件只在「表单已经填对」之后才被打开。
 */
export default function ConfirmModal({
  title,
  children,
  confirmLabel = "确认",
  cancelLabel = "取消",
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label={title}
      onClick={() => { if (!busy) onCancel(); }}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 10000,
        background: "rgba(0,0,0,0.55)",
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
          color: "var(--fg)",
          borderRadius: 8,
          padding: 24,
          width: 420,
          maxWidth: "100%",
          maxHeight: "85vh",
          overflowY: "auto",
          boxShadow: "0 8px 30px rgba(0,0,0,0.25)",
        }}
      >
        <h3 style={{ margin: "0 0 12px", fontSize: 18 }}>{title}</h3>
        <div style={{ color: "var(--muted)", lineHeight: 1.7, margin: "0 0 20px", fontSize: 14 }}>
          {children}
        </div>
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={"btn " + (danger ? "btn-danger" : "btn-primary")}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "处理中…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
