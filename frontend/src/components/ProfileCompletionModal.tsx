import { useEffect } from "react";

/**
 * 实名资料补全提醒（2026-11-12）：登录后真实姓名 / 校牌号还缺时弹一次。
 *
 * 两个出口：
 * - 「下次一定」只在本次登录会话内静默（前端 sessionStorage 标记，不写服务端），
 *   下次登录照弹——提醒会一直跟着，直到资料补齐；
 * - 「立即填写」跳到本人的资料编辑页（/u/<id>?tab=profile）。
 *
 * 深色模式：颜色全部取设计令牌（--bg / --fg / --muted / --faint / --line），
 * 不写死色值，跟随 data-theme 自动切换。手机版共用同一份实现。
 */
export default function ProfileCompletionModal({
  missing,
  onLater,
  onFill,
}: {
  missing: string[];
  onLater: () => void;
  onFill: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onLater();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onLater]);

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label="完善实名资料"
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
        style={{
          background: "var(--bg)",
          color: "var(--fg)",
          // 深色下卡片与 OLED 纯黑页面同色，靠这道细边框勾出卡片轮廓。
          border: "1px solid var(--line)",
          borderRadius: 10,
          padding: "24px 22px",
          width: 400,
          maxWidth: "100%",
          maxHeight: "85vh",
          overflowY: "auto",
          boxShadow: "0 10px 36px rgba(0,0,0,0.28)",
        }}
      >
        <h3 style={{ margin: "0 0 10px", fontSize: 17 }}>还差一步：补全实名资料</h3>
        <p style={{ margin: "0 0 8px", color: "var(--muted)", fontSize: 14, lineHeight: 1.7 }}>
          社团的社员名册、活动签到都要靠实名信息对上人，你还有这些没填：
        </p>
        <ul
          style={{
            margin: "0 0 14px",
            padding: "10px 14px 10px 30px",
            border: "1px solid var(--line)",
            borderRadius: 8,
            color: "var(--fg)",
            fontSize: 14,
            lineHeight: 1.9,
          }}
        >
          {missing.map((label) => (
            <li key={label}>{label}</li>
          ))}
        </ul>
        <p style={{ margin: "0 0 18px", color: "var(--faint)", fontSize: 12.5, lineHeight: 1.7 }}>
          点「下次一定」只跳过本次，下次登录还会提醒；填好之后就不再打扰。
        </p>
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <button type="button" className="btn btn-ghost" onClick={onLater}>
            下次一定
          </button>
          <button type="button" className="btn btn-primary" onClick={onFill}>
            立即填写
          </button>
        </div>
      </div>
    </div>
  );
}
