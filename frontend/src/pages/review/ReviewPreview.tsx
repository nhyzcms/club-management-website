import { useEffect, useState } from "react";
import { newsApi } from "../../api/news";
import { activityApi } from "../../api/activities";
import { tutorialApi, type TutorialItem } from "../../api/tutorials";
import { reviewsApi } from "../../api/reviews";
import type { NewsAttachment, NewsDetail } from "../../types/news";
import {
  ACTIVITY_TYPE_META,
  AUDIENCE_LABELS,
  activityPhase,
  type ActivityDetail,
} from "../../types/activities";
import type { Attachment } from "../../types/tasks";
import {
  REVIEW_STATUS_BADGE,
  REVIEW_STATUS_LABELS,
  TARGET_TYPE_LABELS,
  type ReviewItem,
  type ReviewTargetType,
} from "../../types/reviews";
import "../../styles/news.css";
import "../../styles/detail.css";
import "../../styles/form.css";

const TARGET_PATH: Record<ReviewTargetType, string> = {
  news: "/news",
  activity: "/activity",
  tutorial: "/tutorials",
};

type Loaded =
  | { kind: "news"; data: NewsDetail }
  | { kind: "activity"; data: ActivityDetail }
  | { kind: "tutorial"; data: TutorialItem };

async function fetchTarget(type: ReviewTargetType, id: number): Promise<Loaded> {
  if (type === "news") return { kind: "news", data: await newsApi.get(id) };
  if (type === "activity") return { kind: "activity", data: await activityApi.get(id) };
  return { kind: "tutorial", data: await tutorialApi.get(id) };
}

function surveyQuestionHint(schema: Record<string, unknown> | undefined): string {
  if (!schema) return "问卷未配置";
  const pages = Array.isArray(schema.pages) ? schema.pages : [];
  const root = Array.isArray(schema.elements) ? schema.elements : [];
  let n = root.length;
  for (const page of pages) {
    if (page && typeof page === "object" && Array.isArray((page as { elements?: unknown }).elements)) {
      n += (page as { elements: unknown[] }).elements.length;
    }
  }
  return n > 0 ? `问卷 ${n} 题` : "问卷已配置";
}

function FileMedia({ file }: { file: Attachment | NewsAttachment }) {
  if (file.file_type === "image") {
    return <img src={file.file_url} alt={file.file_name} width={800} height={600} />;
  }
  if (file.file_type === "video") {
    return <video src={file.file_url} controls />;
  }
  return (
    <a href={file.file_url} target="_blank" rel="noreferrer">
      {file.file_name}
    </a>
  );
}

function NewsBody({ news }: { news: NewsDetail }) {
  return (
    <>
      <h2 className="desk-title">{news.title}</h2>
      <div className="desk-sub">
        <span>{news.author.nickname || news.author.username}</span>
        <span className="sep">·</span>
        <span className={"badge " + (news.is_published ? "badge-success" : "badge-ghost")}>
          {news.is_published ? "已上线" : "未上线"}
        </span>
      </div>
      {news.cover_image_url && (
        <div className="desk-cover">
          <img src={news.cover_image_url} alt={news.title} width={800} height={500} />
        </div>
      )}
      {news.content ? (
        <div className="prose" dangerouslySetInnerHTML={{ __html: news.content }} />
      ) : (
        <p className="empty-text">（暂无正文）</p>
      )}
      {news.attachments?.length > 0 && (
        <div className="desk-preview-media">
          {news.attachments.map((att) => (
            <FileMedia key={att.id} file={att} />
          ))}
        </div>
      )}
    </>
  );
}

function ActivityBody({ activity }: { activity: ActivityDetail }) {
  const phase = activityPhase(activity.type, activity.status);
  const typeMeta = ACTIVITY_TYPE_META[activity.type];
  return (
    <>
      <h2 className="desk-title">{activity.title}</h2>
      <div className="desk-sub">
        <span className={"act-medal " + typeMeta.medal}>
          <span className="act-medal-ico">{typeMeta.emoji}</span>
          {typeMeta.label}
        </span>
        <span className={"act-medal " + phase.medalClass}>
          <span className="act-medal-ico">{phase.emoji}</span>
          {phase.label}
        </span>
        {activity.type === "survey" && (
          <span className={"badge " + (activity.audience === "public" ? "badge-brand" : "badge-neutral")}>
            {AUDIENCE_LABELS[activity.audience]}
          </span>
        )}
        {activity.creator && (
          <>
            <span className="sep">·</span>
            <span>{activity.creator.nickname || activity.creator.username}</span>
          </>
        )}
      </div>
      {activity.body ? (
        <div className="prose" dangerouslySetInnerHTML={{ __html: activity.body }} />
      ) : (
        <p className="empty-text">（暂无正文）</p>
      )}
      {activity.type === "deliberation" && (activity.options || []).length > 0 && (
        <ol className="desk-preview-list">
          {(activity.options || []).map((opt) => (
            <li key={opt.id}>{opt.text}</li>
          ))}
        </ol>
      )}
      {activity.type === "exhibition" && (
        (activity.exhibits || []).length > 0 ? (
          <div className="exhibit-grid" style={{ marginTop: "var(--s-4)" }}>
            {(activity.exhibits || []).map((ex) => (
              <div key={ex.id} className="exhibit-card">
                <div className="exhibit-media">
                  {ex.files.map((f) => (
                    <FileMedia key={f.id} file={f} />
                  ))}
                </div>
                <div className="exhibit-title">{ex.title || "未命名"}</div>
              </div>
            ))}
          </div>
        ) : (
          <p className="empty-text">暂无展品。</p>
        )
      )}
      {activity.type === "survey" && (
        <p className="muted" style={{ marginTop: "var(--s-4)" }}>
          {surveyQuestionHint(activity.schema)}
        </p>
      )}
    </>
  );
}

function TutorialBody({ item }: { item: TutorialItem }) {
  const [videoFailed, setVideoFailed] = useState(false);
  return (
    <>
      <h2 className="desk-title">{item.title}</h2>
      <div className="desk-sub">
        <span>{item.uploader.nickname || item.uploader.username}</span>
      </div>
      <div className="desk-preview-media">
        {item.file_type === "video" && item.file_url && !videoFailed ? (
          <video
            controls
            src={item.file_url}
            onError={() => setVideoFailed(true)}
          >
            当前浏览器无法播放该视频，请
            <a href={item.file_url} download={item.file_name}>下载原件</a>。
          </video>
        ) : item.file_type === "video" && item.file_url && videoFailed ? (
          <p className="empty-text">
            当前浏览器无法解码该视频编码，请
            <a href={item.file_url} download={item.file_name}>下载原件</a> 本地播放。
          </p>
        ) : item.file_url ? (
          <p>
            <a className="btn btn-primary" href={item.file_url} download={item.file_name}>
              下载文档（{item.file_name}）
            </a>
          </p>
        ) : null}
      </div>
      {item.description && <p style={{ marginTop: "var(--s-4)" }}>{item.description}</p>}
    </>
  );
}

/**
 * 审核 desk Preview: given a review row (target_type + target_id), fetch the
 * existing retrieve JSON and render publication status, body/media, and moderate
 * actions. Does not mount the public detail pages.
 */
export default function ReviewPreview({
  review,
  flash,
  onModerated,
  onSkip,
}: {
  review: ReviewItem;
  flash?: string;
  onModerated: (updated: ReviewItem, notice: string) => void | Promise<void>;
  onSkip?: () => void;
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectComment, setRejectComment] = useState("");

  const targetType = review.target_type;
  const targetId = review.target_id;

  useEffect(() => {
    if (!targetType || !targetId) {
      setLoaded(null);
      setLoading(false);
      setError("未知审核对象");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    setLoaded(null);
    setRejectOpen(false);
    setRejectComment("");
    fetchTarget(targetType, targetId)
      .then((data) => {
        if (!cancelled) setLoaded(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [targetType, targetId]);

  const run = async (fn: () => Promise<ReviewItem>, notice: string) => {
    setBusy(true);
    setError("");
    try {
      const updated = await fn();
      setRejectOpen(false);
      setRejectComment("");
      await onModerated(updated, notice);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const href = targetType && targetId
    ? `#${TARGET_PATH[targetType]}/${targetId}`
    : "";

  return (
    <div className="desk-pane">
      <div className="desk-toolbar">
        <div className="desk-meta">
          <span className="badge badge-neutral">
            {TARGET_TYPE_LABELS[targetType || ""] || targetType}
          </span>
          <span className={"badge " + REVIEW_STATUS_BADGE[review.status]}>
            {REVIEW_STATUS_LABELS[review.status]}
          </span>
          {flash && <span className="badge badge-brand">{flash}</span>}
          {review.comment && <span className="desk-comment">评语：{review.comment}</span>}
          {href && (
            <a className="btn btn-ghost btn-sm" href={href} target="_blank" rel="noreferrer">
              新标签打开
            </a>
          )}
        </div>
        <div className="desk-actions">
          {review.status === "pending" && (
            <>
              <button
                className="btn btn-primary"
                disabled={busy}
                onClick={() => void run(() => reviewsApi.approve(review.id), "已通过")}
              >
                通过
              </button>
              <button
                className="btn btn-ghost"
                disabled={busy}
                onClick={() => { setRejectOpen(true); setRejectComment(""); }}
              >
                驳回
              </button>
            </>
          )}
          {review.status === "approved" && (
            <button
              className="btn btn-ghost"
              disabled={busy}
              onClick={() => void run(() => reviewsApi.remove(review.id), "已下架")}
            >
              下架
            </button>
          )}
          {onSkip && (
            <button className="btn btn-ghost" disabled={busy} onClick={onSkip}>
              下一条
            </button>
          )}
        </div>
        {rejectOpen && review.status === "pending" && (
          <div style={{ marginTop: 12 }}>
            <textarea
              className="input"
              rows={3}
              placeholder="驳回评语（必填）"
              value={rejectComment}
              onChange={(e) => setRejectComment(e.target.value)}
            />
            <div className="form-actions" style={{ marginTop: 8 }}>
              <button className="btn btn-ghost btn-sm" onClick={() => setRejectOpen(false)}>取消</button>
              <button
                className="btn btn-primary btn-sm"
                disabled={!rejectComment.trim() || busy}
                onClick={() => void run(
                  () => reviewsApi.reject(review.id, rejectComment.trim()),
                  "已驳回",
                )}
              >
                确认驳回
              </button>
            </div>
          </div>
        )}
      </div>
      {error && <div className="alert alert-warning" style={{ marginBottom: 12 }}>{error}</div>}
      <div className="desk-target">
        {loading ? (
          <p className="task-empty">加载中…</p>
        ) : loaded?.kind === "news" ? (
          <NewsBody news={loaded.data} />
        ) : loaded?.kind === "activity" ? (
          <ActivityBody activity={loaded.data} />
        ) : loaded?.kind === "tutorial" ? (
          <TutorialBody item={loaded.data} />
        ) : null}
      </div>
    </div>
  );
}
