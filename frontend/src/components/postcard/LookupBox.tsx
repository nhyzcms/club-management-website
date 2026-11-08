import { useState } from "react";
import type { PostcardPortal, PostcardRegistrationSummary } from "../../api/postcard";
import { postcardApi } from "../../api/postcard";
import HistorySection from "./HistorySection";

interface Props {
  portal: PostcardPortal;
  fingerprint: string;
  isMobile: boolean;
  /** 查询结果里发生修改/取消后：刷新页面历史列表。 */
  onChanged: () => void;
}

export interface LookupResult {
  kind: "code" | "name";
  results: PostcardRegistrationSummary[];
}

/**
 * 用户侧查询入口（2026-11-08 用户要求）：按 6 位登记码或寄出人姓名找回登记。
 *
 * - **登记码** = 能力凭证：返回完整记录，可直接改 / 取消 / 申请复核
 *   （换设备、清 Cookie 也能用）；
 * - **姓名**：只返回掩码结果（登记码 `82****`、无照片），用于确认登记是否存在
 *   及状态；修改必须出示完整登记码——防止任何人凭姓名改他人记录。
 */
export default function LookupBox({ portal, fingerprint, isMobile, onChanged }: Props) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<LookupResult | null>(null);

  const runQuery = async (raw: string) => {
    const query = raw.trim();
    if (!query || busy) return;
    setBusy(true);
    setError("");
    try {
      const data = await postcardApi.lookup(query);
      setResult(data);
    } catch (err: any) {
      setError(err?.message || "查询失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  };

  const primaryBtn = isMobile ? "m-btn-primary" : "btn btn-primary";
  const ghostBtn = isMobile ? "m-btn-ghost" : "btn btn-ghost";

  return (
    <div className="pc-lookup">
      <form
        className="pc-lookup-form"
        onSubmit={(e) => {
          e.preventDefault();
          void runQuery(q);
        }}
      >
        <input
          className="input"
          autoComplete="off"
          maxLength={64}
          placeholder="6 位登记码，或寄出人姓名"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button type="submit" className={primaryBtn} disabled={busy || !q.trim()}>
          {busy ? "查询中…" : "查询"}
        </button>
      </form>

      {error && (
        <div className="alert alert-danger" role="alert">
          <span>{error}</span>
        </div>
      )}

      {result && result.results.length === 0 && (
        <p className="muted pc-lookup-empty">
          {result.kind === "code"
            ? "没有找到该登记码对应的记录，请核对 6 位数字。"
            : "没有找到该姓名的登记记录（姓名须与登记时完全一致）。"}
        </p>
      )}

      {result && result.results.length > 0 && result.kind === "code" && (
        <div className="pc-lookup-full">
          <p className="pc-lookup-found">找到登记记录，可直接在此修改或取消：</p>
          <HistorySection
            regs={result.results}
            portal={portal}
            fingerprint={fingerprint}
            isMobile={isMobile}
            onChanged={() => {
              onChanged();
              // 结果也要跟着刷新（例如取消后状态变「已取消」）
              void runQuery(q);
            }}
          />
        </div>
      )}

      {result && result.results.length > 0 && result.kind === "name" && (
        <div className="pc-lookup-masked">
          <p className="pc-lookup-found">按姓名找到 {result.results.length} 条登记：</p>
          <ul className="pc-lookup-list">
            {result.results.map((r) => (
              <li key={`${r.sender_name}-${r.created_at}-${r.reg_code}`} className="pc-lookup-item">
                <div className="pc-lookup-line">
                  <strong>{r.sender_name}</strong>
                  <span className="muted">
                    {r.grade_label} {r.class_no} 班 → {r.dest_region} {r.dest_school}
                  </span>
                  <span className="pc-badge">{r.status_label}</span>
                </div>
                <div className="pc-lookup-line muted">
                  <span>登记码 {r.reg_code}</span>
                  <span>条码：{r.items.map((it) => it.barcode).join("、") || "—"}</span>
                </div>
              </li>
            ))}
          </ul>
          <p className="muted pc-lookup-hint">
            姓名查询只显示掩码登记码。要修改 / 取消 / 申请人工复核，请用完整的 6 位登记码查询。
          </p>
        </div>
      )}

      {!result && !error && (
        <p className="muted pc-lookup-hint">
          姓名查询可确认登记是否成功；修改与取消需要完整登记码。
        </p>
      )}
    </div>
  );
}
