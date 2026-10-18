import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { messagingApi } from "../api/messaging";
import { onMessagingEvent, onMessagingOpen, subscribeThread, unsubscribeThread } from "../api/messagingSocket";
import { api } from "../api/client";
import { useSitePolicy } from "../api/sitePolicy";
import { useEmbedMode } from "../embed";
import { useLoginModal } from "./LoginModalProvider";
import { highlightMentions, MentionTextarea } from "./MentionField";
import ReportButton from "./ReportButton";
import Avatar from "./Avatar";
import type { Comment, CommentHost, CommentThread, ThreadStatus } from "../types/messaging";
import { THREAD_STATUS_LABELS, hostQuery, withinRetractWindow } from "../types/messaging";
import type { TaskUser } from "../types/tasks";
import "../styles/comments.css";

function mapTree(nodes: Comment[], fn: (c: Comment) => Comment): Comment[] {
  return nodes.map((n) => {
    const mapped = fn(n);
    return { ...mapped, replies: mapTree(mapped.replies || [], fn) };
  });
}

function insertComment(roots: Comment[], comment: Comment): Comment[] {
  const node = { ...comment, replies: comment.replies || [] };
  if (!comment.parent) return [...roots, node];
  return mapTree(roots, (c) => (
    c.id === comment.parent ? { ...c, replies: [...(c.replies || []), node] } : c
  ));
}

function renderBody(text: string) {
  return highlightMentions(text);
}

function CommentItem({
  comment,
  depth,
  maxDepth,
  currentUser,
  canManage,
  canReply,
  now,
  busyId,
  onReply,
  onRetract,
  onDelete,
}: {
  comment: Comment;
  depth: number;
  maxDepth: number;
  currentUser: TaskUser | null;
  canManage: boolean;
  canReply: boolean;
  now: number;
  busyId: number | null;
  onReply: (parent: Comment) => void;
  onRetract: (c: Comment) => void;
  onDelete: (c: Comment) => void;
}) {
  const gone = !!(comment.deleted_at || comment.retracted_at);
  const body = comment.deleted_at
    ? "该评论已删除"
    : comment.retracted_at
      ? "该评论已撤回"
      : comment.content;
  const isMine = currentUser?.id === comment.author.id;
  const leaf = (comment.replies || []).length === 0;
  const showRetract = isMine && !gone && leaf && withinRetractWindow(comment.created_at, now);
  const showDelete = canManage && !comment.deleted_at;
  const showReply = canReply && depth < maxDepth && !comment.retracted_at;
  const showReport = !gone && !isMine;

  return (
    <div className={"comment-item" + (depth > 1 ? " is-nested" : "")}>
      <div className="comment-meta">
        <Link to={`/u/${comment.author.id}`}><Avatar user={comment.author} size="sm" /></Link>
        <Link to={`/u/${comment.author.id}`}>{comment.author.nickname || comment.author.username}</Link>
        <span className="comment-time">{new Date(comment.created_at).toLocaleString("zh-CN")}</span>
      </div>
      <div className={"comment-body" + (gone ? " is-gone" : "")}>
        {gone ? body : renderBody(body)}
      </div>
      {(showReply || showRetract || showDelete || showReport) && (
        <div className="comment-actions">
          {showReply && (
            <button className="btn btn-ghost" type="button" onClick={() => onReply(comment)}>回复</button>
          )}
          {showRetract && (
            <button className="btn btn-ghost" type="button" disabled={busyId === comment.id} onClick={() => onRetract(comment)}>撤回</button>
          )}
          {showDelete && (
            <button className="btn btn-ghost" type="button" disabled={busyId === comment.id} onClick={() => onDelete(comment)}>删除</button>
          )}
          {showReport && (
            <ReportButton targetType="comment" targetId={comment.id} ownerId={comment.author.id} compact />
          )}
        </div>
      )}
      {(comment.replies || []).map((child) => (
        <CommentItem
          key={child.id}
          comment={child}
          depth={depth + 1}
          maxDepth={maxDepth}
          currentUser={currentUser}
          canManage={canManage}
          canReply={canReply}
          now={now}
          busyId={busyId}
          onReply={onReply}
          onRetract={onRetract}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}

export default function CommentSection({ host }: { host: CommentHost }) {
  const embed = useEmbedMode();
  const policy = useSitePolicy();
  const { openLogin } = useLoginModal();
  const [thread, setThread] = useState<CommentThread | null>(null);
  const [hidden, setHidden] = useState(false);
  const [roots, setRoots] = useState<Comment[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [currentUser, setCurrentUser] = useState<TaskUser | null>(null);
  const [verified, setVerified] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);
  const [siteMuted, setSiteMuted] = useState(false);
  const [draft, setDraft] = useState("");
  const [replyTo, setReplyTo] = useState<Comment | null>(null);
  const [sending, setSending] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const maxDepth = policy.comment_max_depth || 8;
  const hostKey = JSON.stringify(hostQuery(host));

  const loadComments = useCallback((threadId: number, pageNum = 1, append = false) => {
    return messagingApi.listComments(threadId, pageNum)
      .then((d) => {
        setRoots((prev) => append ? [...prev, ...(d.results || [])] : (d.results || []));
        setCount(typeof d.count === "number" ? d.count : 0);
        setHasMore(d.next != null);
        setPage(pageNum);
      })
      .catch(() => {
        if (!append) setRoots([]);
      });
  }, []);

  useEffect(() => {
    if (embed) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    messagingApi.getThread(host)
      .then((t) => {
        if (cancelled) return null;
        setThread(t);
        setHidden(false);
        return t;
      })
      .catch((err: { status?: number }) => {
        if (!cancelled && err?.status === 404) { setThread(null); setHidden(true); }
        return null;
      })
      .then((t) => {
        if (cancelled || !t) return;
        return loadComments(t.id, 1, false);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // host 以 query 键稳定，避免父组件每次 render 新对象导致重拉
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [embed, hostKey, loadComments]);

  useEffect(() => {
    if (embed) return;
    api.me()
      .then((d: any) => {
        setLoggedIn(true);
        setVerified(!!d.profile?.is_verified);
        setCurrentUser({
          id: d.user.id,
          username: d.user.username,
          email: d.user.email || "",
          nickname: d.profile?.nickname || "",
          avatar: d.profile?.avatar ?? null,
        });
        messagingApi.myMute()
          .then((m) => setSiteMuted(!!m.muted))
          .catch(() => setSiteMuted(false));
      })
      .catch(() => { setLoggedIn(false); setVerified(false); setCurrentUser(null); setSiteMuted(false); });
  }, [embed]);

  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 15000);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    if (!thread) return;
    const threadId = thread.id;
    subscribeThread(threadId);
    const refetch = () => {
      messagingApi.getThread(host).then(setThread).catch(() => {});
      loadComments(threadId, 1, false);
    };
    const offOpen = onMessagingOpen(refetch);
    const offEv = onMessagingEvent((ev) => {
      if (ev.event !== "comment") return;
      if (Number(ev.payload?.thread_id) === threadId) refetch();
    });
    return () => {
      unsubscribeThread(threadId);
      offOpen();
      offEv();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [thread?.id, loadComments]);

  if (embed || hidden || (!loading && !thread)) return null;

  const canManage = !!thread?.can_manage;
  const canPost = !!thread && thread.status === "open" && loggedIn && verified && !siteMuted;
  const composerHint = !loggedIn
    ? "登录后参与评论"
    : !verified
      ? "认证后才能发言"
      : siteMuted
        ? "你已被全站禁言，暂时不能发言"
        : thread?.status === "muted"
          ? "评论区已禁言"
          : thread?.status === "closed"
            ? "评论区已彻底关闭"
            : "写下评论，@ 可搜索并提及他人";

  const submit = async () => {
    if (!thread || !draft.trim() || sending || !canPost) return;
    setSending(true);
    setError("");
    try {
      const created = await messagingApi.postComment(thread.id, draft.trim(), replyTo?.id);
      setRoots((prev) => insertComment(prev, created));
      if (!replyTo) setCount((c) => c + 1);
      setDraft("");
      setReplyTo(null);
    } catch (err: any) {
      setError(err?.message || "发表失败");
    } finally {
      setSending(false);
    }
  };

  const retract = async (c: Comment) => {
    setBusyId(c.id);
    setError("");
    try {
      const updated = await messagingApi.retractComment(c.id);
      setRoots((prev) => mapTree(prev, (n) => (n.id === updated.id ? { ...n, ...updated, replies: n.replies } : n)));
    } catch (err: any) {
      setError(err?.message || "撤回失败");
    } finally {
      setBusyId(null);
    }
  };

  const tombstone = async (c: Comment) => {
    if (!window.confirm("删除后显示「该评论已删除」，回复仍保留。确定？")) return;
    setBusyId(c.id);
    setError("");
    try {
      const updated = await messagingApi.deleteComment(c.id);
      setRoots((prev) => mapTree(prev, (n) => (n.id === updated.id ? { ...n, ...updated, replies: n.replies } : n)));
    } catch (err: any) {
      setError(err?.message || "删除失败");
    } finally {
      setBusyId(null);
    }
  };

  const setStatus = async (status: ThreadStatus) => {
    if (!thread || status === thread.status) return;
    setError("");
    try {
      const updated = await messagingApi.patchThread(thread.id, status);
      setThread(updated);
    } catch (err: any) {
      setError(err?.message || "无法改评论区状态");
    }
  };

  if (!policy.comments_enabled) {
    // 站点策略关闭评论区：整个组件不渲染（新闻 / 活动 / 任务详情页随之隐藏）。
    return null;
  }

  return (
    <section className="comment-section card card-pad">
      <div className="comment-head">
        <h3 className="section-h">评论{!loading ? `（${count}）` : ""}</h3>
        {canManage && thread && (
          <div className="seg seg-sm" role="radiogroup" aria-label="评论区状态">
            {(["open", "muted", "closed"] as ThreadStatus[]).map((s) => (
              <button
                key={s}
                type="button"
                className="seg-btn"
                aria-selected={thread.status === s}
                onClick={() => setStatus(s)}
              >
                {THREAD_STATUS_LABELS[s]}
              </button>
            ))}
          </div>
        )}
      </div>
      {thread?.status === "muted" && (
        <p className="comment-status-note">评论区已禁言：已有评论仍可见，不能再发言。</p>
      )}
      {thread?.status === "closed" && canManage && (
        <p className="comment-status-note">评论区已彻底关闭：普通读者看不到该区。</p>
      )}
      {error && <div className="alert alert-danger" style={{ marginBottom: "var(--s-3)" }}><span>{error}</span></div>}
      {loading ? (
        <p className="empty-text">加载中…</p>
      ) : roots.length === 0 ? (
        <p className="empty-text">还没有评论</p>
      ) : (
        <div className="comment-list">
          {roots.map((c) => (
            <CommentItem
              key={c.id}
              comment={c}
              depth={1}
              maxDepth={maxDepth}
              currentUser={currentUser}
              canManage={canManage}
              canReply={canPost}
              now={now}
              busyId={busyId}
              onReply={(parent) => { setReplyTo(parent); setDraft((d) => d || `@${parent.author.username} `); }}
              onRetract={retract}
              onDelete={tombstone}
            />
          ))}
        </div>
      )}
      {hasMore && thread && (
        <button
          className="btn btn-ghost btn-sm"
          type="button"
          disabled={loadingMore}
          style={{ marginTop: "var(--s-3)" }}
          onClick={() => {
            setLoadingMore(true);
            loadComments(thread.id, page + 1, true).finally(() => setLoadingMore(false));
          }}
        >
          {loadingMore ? "加载中…" : "加载更多评论"}
        </button>
      )}

      <div className="comment-composer">
        {replyTo && (
          <div className="comment-status-note">
            回复 {replyTo.author.nickname || replyTo.author.username}
            {" "}
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => setReplyTo(null)}>取消</button>
          </div>
        )}
        <MentionTextarea
          className="textarea"
          value={draft}
          onChange={setDraft}
          placeholder={composerHint}
          disabled={!canPost}
          rows={3}
          excludeIds={currentUser ? [currentUser.id] : []}
        />
        <div className="comment-composer-row">
          {!loggedIn && (
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => openLogin()}>登录</button>
          )}
          <button className="btn btn-primary" type="button" onClick={submit} disabled={!canPost || !draft.trim() || sending}>
            {sending ? "发送中…" : "发表"}
          </button>
        </div>
      </div>
    </section>
  );
}
