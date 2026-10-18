import { useState, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { messagingApi } from "../api/messaging";
import { onMessagingEvent, onMessagingOpen } from "../api/messagingSocket";
import { api } from "../api/client";
import { useSitePolicy } from "../api/sitePolicy";
import type { TaskUser } from "../types/tasks";
import type { Conversation } from "../types/messaging";
import type { Paginated } from "../types/pagination";
import { usePagedList } from "../hooks/usePagedList";
import Pagination from "../components/Pagination";
import Avatar from "../components/Avatar";
import AppShell from "../components/AppShell";
import MessageThread from "../components/MessageThread";
import UserSearchSelect, { type SelectUser } from "../components/UserSearchSelect";
import { useLoginModal } from "../components/LoginModalProvider";
import "../styles/messages.css";

const PAGE_SIZE = 20;

function preview(conv: Conversation): string {
  const last = conv.last_message;
  if (!last) return "暂无消息";
  if (last.retracted_at) return "该消息已撤回";
  return last.content?.slice(0, 40) || "暂无消息";
}

export default function MessagePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { openLogin } = useLoginModal();
  const policy = useSitePolicy();
  const [user, setUser] = useState<TaskUser | null>(null);
  const [verified, setVerified] = useState(false);
  const [activeConv, setActiveConv] = useState<Conversation | null>(null);
  const [composing, setComposing] = useState(false);
  const [startError, setStartError] = useState("");
  const [starting, setStarting] = useState(false);

  const { data: conversations, page, setPage, totalPages, loading: convLoading, refetch } = usePagedList<Conversation>(
    (params) => messagingApi.listConversations(params) as Promise<Paginated<Conversation>>,
    PAGE_SIZE,
  );

  useEffect(() => {
    document.title = "私信 · 传媒社";
  }, []);

  useEffect(() => {
    api.me()
      .then((d) => {
        setUser({ ...d.user, avatar: d.profile.avatar, nickname: d.profile.nickname });
        setVerified(!!d.profile?.is_verified);
      })
      .catch(() => openLogin());
  }, [openLogin]);

  useEffect(() => {
    if (!id) return;
    messagingApi.getConversation(Number(id))
      .then((conv) => setActiveConv(conv))
      .catch(console.error);
  }, [id]);

  useEffect(() => {
    const refresh = () => {
      refetch();
      if (id) {
        messagingApi.getConversation(Number(id)).then(setActiveConv).catch(() => {});
      }
    };
    const offOpen = onMessagingOpen(refresh);
    const offEv = onMessagingEvent((ev) => {
      if (ev.event === "dm" || ev.event === "unread") refresh();
    });
    return () => { offOpen(); offEv(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const startWith = async (u: SelectUser) => {
    if (starting) return;
    setStarting(true);
    setStartError("");
    try {
      const conv = await messagingApi.startPrivate(u.id);
      setComposing(false);
      await refetch();
      setActiveConv(conv);
      navigate(`/messages/${conv.id}`, { replace: true });
    } catch (e: any) {
      setStartError(e?.message || "无法发起私信");
    } finally {
      setStarting(false);
    }
  };

  const selectConversation = (conv: Conversation) => {
    setActiveConv(conv);
    navigate(`/messages/${conv.id}`, { replace: true });
  };

  const getConvTitle = (conv: Conversation) => {
    const other = conv.participants.find((p) => p.id !== user?.id);
    return other?.nickname || other?.username || conv.title || "私人会话";
  };

  const activeOther = activeConv?.participants.find((p) => p.id !== user?.id);
  const peerDeleted = !!activeOther?.is_deleted;

  if (!policy.dms_enabled) {
    // 站点策略关闭私信：页面兜底（入口已隐藏，直接访问 URL 时给提示）。
    return (
      <AppShell>
        <div className="container" style={{ padding: "var(--s-16)" }}>
          <div className="prop-empty">
            <p>私信功能已关闭。</p>
            <p className="muted">管理员已在站点策略中关闭私信功能。</p>
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <span>私信</span>
          </nav>
          <div className="page-head-row">
            <h1>私信</h1>
          </div>
        </div>
      </div>

      <div className="container">
        <div className="msg-layout">
          <div className="msg-side">
            <div className="msg-side-head">
              <span>会话</span>
              <button
                className="btn btn-ghost btn-sm"
                type="button"
                disabled={!verified}
                title={verified ? "搜索用户发起私信" : "认证后才能发私信"}
                onClick={() => { setComposing((v) => !v); setStartError(""); }}
              >
                {composing ? "取消" : "写私信"}
              </button>
            </div>
            {composing && (
              <div className="msg-compose">
                {verified ? (
                  <UserSearchSelect
                    selected={[]}
                    single
                    excludeIds={user ? [user.id] : []}
                    placeholder={starting ? "正在打开…" : "搜索用户发起私信…"}
                    onChange={(users) => { if (users[0]) startWith(users[0]); }}
                  />
                ) : (
                  <p className="msg-compose-hint">认证后才能发私信</p>
                )}
                {startError && <p className="msg-compose-error">{startError}</p>}
              </div>
            )}
            <div className="msg-list">
              {convLoading ? (
                <div className="msg-list-empty">加载中…</div>
              ) : conversations.length === 0 ? (
                <div className="msg-list-empty">暂无私信</div>
              ) : (
                conversations.map((conv) => (
                  <button
                    key={conv.id}
                    className={`msg-list-item${activeConv?.id === conv.id ? " active" : ""}`}
                    onClick={() => selectConversation(conv)}
                  >
                    <div className="ml-top">
                      <span className="ml-title">{getConvTitle(conv)}</span>
                      <span className="ml-meta">
                        {conv.unread_count > 0 && (
                          <span className="msg-badge">{conv.unread_count}</span>
                        )}
                      </span>
                    </div>
                    <div className="ml-preview">{preview(conv)}</div>
                  </button>
                ))
              )}
            </div>
            {!convLoading && conversations.length > 0 && (
              <Pagination
                page={page}
                totalPages={totalPages}
                onChange={setPage}
                style={{ marginTop: "var(--s-2)", paddingBottom: "var(--s-3)" }}
              />
            )}
          </div>

          <div className="msg-thread">
            {activeConv ? (
              <>
                <div className="msg-thread-head">
                  {activeOther && <Link to={`/u/${activeOther.id}`}><Avatar user={activeOther} size="md" /></Link>}
                  <h3>{getConvTitle(activeConv)}</h3>
                </div>
                {user && (
                  <MessageThread
                    conversationId={activeConv.id}
                    currentUser={user}
                    peerDeleted={peerDeleted}
                  />
                )}
              </>
            ) : (
              <div className="msg-empty">选择一个会话，或点「写私信」搜索用户开始聊天</div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
