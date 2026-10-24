import { SupersedeTakeover, sessionEndedMessage } from "../api/shared";

/** 下线原因 → 标题（ADR-0028 多端登录：名额顶替 / 手动下线 / 设备重登 / 安全吊销）。 */
function titleFor(reason?: string): string {
  switch (reason) {
    case "limit":
      return "设备名额已满";
    case "manual":
      return "该设备已被下线";
    case "replaced":
      return "该设备已重新登录";
    case "security":
      return "账号安全状态已变更";
    default:
      return "账号在其他设备登录";
  }
}

export default function SessionSupersedeModal({
  takeover,
  revokedReason,
  onConfirm,
}: {
  takeover: SupersedeTakeover | null;
  revokedReason?: string;
  onConfirm: () => void;
}) {
  if (!takeover) return null;

  const when = takeover.time ? new Date(takeover.time).toLocaleString("zh-CN") : "";
  const where = [takeover.device_name, takeover.ip ? `IP ${takeover.ip}` : ""]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
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
        <h3 style={{ margin: "0 0 12px", fontSize: 18 }}>{titleFor(revokedReason)}</h3>
        <p style={{ color: "var(--muted)", lineHeight: 1.6, margin: "0 0 8px" }}>
          {sessionEndedMessage(revokedReason)}
        </p>
        {(when || where) && (
          <p style={{ color: "var(--faint)", fontSize: 13, margin: "0 0 8px" }}>
            {where ? `当前登录设备：${where}` : ""}
            {when ? `${where ? "，" : ""}登录于 ${when}` : ""}
          </p>
        )}
        <p style={{ color: "var(--faint)", fontSize: 13, margin: "0 0 16px" }}>
          如非本人操作，请及时修改密码。
        </p>
        <button
          onClick={onConfirm}
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
          重新登录
        </button>
      </div>
    </div>
  );
}
