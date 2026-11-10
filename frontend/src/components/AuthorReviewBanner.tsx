import type { ReviewStatus } from "../types/reviews";
import "../styles/form.css";

const NOUN: Record<"news" | "activity" | "tutorial", string> = {
  news: "稿",
  activity: "活动",
  tutorial: "教程",
};

export default function AuthorReviewBanner({
  status,
  comment,
  kind,
  extra,
}: {
  status?: ReviewStatus | null;
  comment?: string | null;
  kind: "news" | "activity" | "tutorial";
  extra?: string;
}) {
  if (!status || status === "approved") return null;
  const noun = NOUN[kind];
  const reason = (comment || "").trim();
  if (status === "pending") {
    return (
      <div className="form-notice" style={{ margin: "12px 0" }}>
        此{noun}待审，仅作者与审核员可见，尚未对公众公开。
        {extra ? <div style={{ marginTop: 6 }}>{extra}</div> : null}
      </div>
    );
  }
  const title = status === "rejected"
    ? `此${noun}已驳回，不对公众展示。`
    : `此${noun}已下架，不对公众展示。`;
  return (
    <div className="alert alert-warning" style={{ margin: "12px 0" }}>
      <span>
        {title}
        {reason ? ` 评语：${reason}` : ""}
      </span>
    </div>
  );
}
