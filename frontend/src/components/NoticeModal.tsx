import { useEffect } from "react";

/**
 * 通用提示弹窗：用于「必须打断用户」的一次性提示（如邮箱后缀不在白名单）。
 * 自包含 inline 样式，与 SessionSupersedeModal 同风格（不引新 CSS 依赖）。
 * 关闭途径：确认按钮 / 点遮罩 / Esc。
 */
export default function NoticeModal({
  title = "提示",
  message,
  confirmLabel = "我知道了",
  onClose,
}: {
  title?: string;
  message: string;
  confirmLabel?: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg)",
          borderRadius: 8,
          padding: 24,
          width: 380,
          maxWidth: "90vw",
          textAlign: "center",
          boxShadow: "0 8px 30px rgba(0,0,0,0.2)",
        }}
      >
        <h3 style={{ margin: "0 0 12px", fontSize: 18 }}>{title}</h3>
        <p style={{ color: "var(--muted)", lineHeight: 1.6, margin: "0 0 16px" }}>{message}</p>
        <button
          type="button"
          onClick={onClose}
          style={{
            padding: "8px 20px",
            background: "#2563eb",
            color: "#fff",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
            fontSize: 14,
          }}
        >
          {confirmLabel}
        </button>
      </div>
    </div>
  );
}
