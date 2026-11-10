import { MEMBER_STATUS_LABELS } from "../../types/member";

/** 社员公开信息（扫码校验 / 社员查询共用；后端只下发这几个字段）。 */
export interface MemberPublicResult {
  name?: string;
  cohort?: number;
  code?: string;
  status?: string;
  avatar?: string | null;
}

/**
 * 社员公开信息卡：工牌二维码扫码结果与「社员查询」结果**同一组件**，
 * 保证两条入口看到的字段、层级、徽标完全一致。
 */
export default function MemberResultCard({
  result,
  note = "本页来自工牌二维码，仅展示公开信息。",
}: {
  result: MemberPublicResult;
  note?: string;
}) {
  const statusLabel = result.status
    ? MEMBER_STATUS_LABELS[result.status] ?? result.status
    : "";
  return (
    <>
      {result.avatar && <img className="member-verify-avatar" src={result.avatar} alt="" />}
      <div className="member-verify-name">{result.name}</div>
      <p className="muted">第 {result.cohort} 届</p>
      <p>
        <span
          className={"badge " + (result.status === "active" ? "badge-success" : "badge-ghost")}
        >
          {statusLabel}
        </span>
      </p>
      <p className="muted member-verify-code">识别码 {result.code}</p>
      <p className="muted">{note}</p>
    </>
  );
}
