import type { ThreadStatus } from "../types/messaging";
import { THREAD_STATUS_LABELS } from "../types/messaging";

const ORDER: ThreadStatus[] = ["open", "muted", "closed"];

export default function CommentThreadStatusField({
  value,
  onChange,
  disabled = false,
}: {
  value: ThreadStatus;
  onChange: (status: ThreadStatus) => void;
  disabled?: boolean;
}) {
  return (
    <div className="field">
      <label className="label">评论区</label>
      <div className="seg" role="radiogroup" aria-label="评论区状态">
        {ORDER.map((s) => (
          <button
            key={s}
            type="button"
            className="seg-btn"
            aria-selected={value === s}
            disabled={disabled}
            onClick={() => onChange(s)}
          >
            {THREAD_STATUS_LABELS[s]}
          </button>
        ))}
      </div>
      <div className="hint">
        开放可发言；评论区禁言只读已有评论；彻底关闭后普通读者看不到该区。
      </div>
    </div>
  );
}
