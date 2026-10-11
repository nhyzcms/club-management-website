import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { messagingApi } from "../api/messaging";
import { emitMessagingEvent, onMessagingEvent, onMessagingOpen } from "../api/messagingSocket";
import type { DirectMessage } from "../types/messaging";
import { withinRetractWindow } from "../types/messaging";
import type { TaskUser } from "../types/tasks";
import Avatar from "./Avatar";
import { highlightMentions, MentionInput } from "./MentionField";
import "../styles/messages.css";

/**
 * 1:1 私信线程：倒序分页（最新优先，向上加载更早）。
 * 发送 / 撤回走 HTTP；WS 推送时合并最新一页。全站禁言时禁用输入。
 */
export default function MessageThread({
  conversationId,
  currentUser,
  autoScroll = true,
  onCountChange,
}: {
  conversationId: number;
  currentUser: TaskUser;
  autoScroll?: boolean;
  onCountChange?: (count: number) => void;
}) {
  const [messages, setMessages] = useState<DirectMessage[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [siteMuted, setSiteMuted] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const listRef = useRef<HTMLDivElement>(null);
  const countRef = useRef(0);
  const pinToBottom = useRef(true);

  const mergeLatest = (latest: DirectMessage[]) => {
    const chronological = [...latest].reverse();
    setMessages((prev) => {
      const byId = new Map<number, DirectMessage>();
      prev.forEach((m) => byId.set(m.id, m));
      chronological.forEach((m) => byId.set(m.id, m));
      return [...byId.values()].sort(
        (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
      );
    });
  };

  const markRead = () =>
    messagingApi.markRead(conversationId).then(() => {
      emitMessagingEvent({ event: "unread", payload: { conversation_id: conversationId } });
    }).catch(() => {});

  useLayoutEffect(() => {
    if (!autoScroll || loading || !pinToBottom.current) return;
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, loading, autoScroll]);

  useEffect(() => {
    let cancelled = false;
    pinToBottom.current = true;
    setLoading(true);
    setMessages([]);
    setPage(1);
    setError("");
    messagingApi
      .getMessages(conversationId, 1)
      .then((d) => {
        if (cancelled) return;
        setMessages([...d.results].reverse());
        setHasMore(d.next != null);
        countRef.current = d.count;
        onCountChange?.(d.count);
      })
      .catch(console.error)
      .finally(() => { if (!cancelled) setLoading(false); });
    markRead();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  useEffect(() => {
    messagingApi.myMute().then((d) => setSiteMuted(!!d.muted)).catch(() => setSiteMuted(false));
  }, [conversationId]);

  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 15000);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    const pull = () => {
      messagingApi.getMessages(conversationId, 1).then((d) => {
        mergeLatest(d.results);
        countRef.current = d.count;
        onCountChange?.(d.count);
      }).catch(() => {});
    };
    const offOpen = onMessagingOpen(pull);
    const offEv = onMessagingEvent((ev) => {
      if (ev.event !== "dm") return;
      if (Number(ev.payload?.conversation_id) === conversationId) {
        pull();
        markRead();
      }
    });
    return () => { offOpen(); offEv(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  const loadEarlier = async () => {
    if (loadingMore) return;
    setLoadingMore(true);
    pinToBottom.current = false;
    const next = page + 1;
    const prevHeight = listRef.current?.scrollHeight ?? 0;
    try {
      const d = await messagingApi.getMessages(conversationId, next);
      setMessages((prev) => [...d.results].reverse().concat(prev));
      setPage(next);
      setHasMore(d.next != null);
      requestAnimationFrame(() => {
        const el = listRef.current;
        if (el) el.scrollTop = el.scrollHeight - prevHeight;
      });
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingMore(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || sending || siteMuted) return;
    setSending(true);
    setError("");
    try {
      const m = await messagingApi.sendMessage(conversationId, input.trim());
      pinToBottom.current = true;
      setMessages((prev) => [...prev, m]);
      setInput("");
      countRef.current += 1;
      onCountChange?.(countRef.current);
    } catch (err: any) {
      setError(err?.message || "发送失败");
    } finally {
      setSending(false);
    }
  };

  const handleRetract = async (m: DirectMessage) => {
    setError("");
    try {
      const updated = await messagingApi.retractMessage(conversationId, m.id);
      setMessages((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
    } catch (err: any) {
      setError(err?.message || "撤回失败");
    }
  };

  return (
    <>
      <div
        className="msg-bubbles"
        ref={listRef}
        onScroll={() => {
          const el = listRef.current;
          if (!el) return;
          pinToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
      >
        {loading ? (
          <div className="msg-empty">加载中…</div>
        ) : (
          <>
            {hasMore && (
              <button className="msg-load-more" onClick={loadEarlier} disabled={loadingMore}>
                {loadingMore ? "加载中…" : "加载更早的消息"}
              </button>
            )}
            {messages.length === 0 ? (
              <div className="msg-empty">暂无消息，开始聊天吧</div>
            ) : (
              messages.map((m) => {
                const mine = m.sender.id === currentUser.id;
                const retracted = !!m.retracted_at;
                const canRetract = mine && !retracted && withinRetractWindow(m.created_at, now);
                return (
                  <div
                    key={m.id}
                    className={"msg-bubble" + (mine ? " mine" : "") + (retracted ? " is-retracted" : "")}
                  >
                    {!mine && (
                      <div className="mb-author">
                        <Link to={`/u/${m.sender.id}`}><Avatar user={m.sender} /></Link>
                        {m.sender.nickname || m.sender.username}
                      </div>
                    )}
                    <div className="mb-content">{retracted ? "该消息已撤回" : highlightMentions(m.content)}</div>
                    <div className="mb-time">
                      {new Date(m.created_at).toLocaleString("zh-CN")}
                      {canRetract && (
                        <button className="mb-retract" type="button" onClick={() => handleRetract(m)}>撤回</button>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </>
        )}
      </div>
      {error && <div className="msg-error" role="alert">{error}</div>}
      <div className="msg-input">
        <MentionInput
          className="input"
          value={input}
          onChange={setInput}
          placeholder={siteMuted ? "你已被全站禁言，暂时不能发言" : "输入消息，@ 可搜索并提及他人"}
          disabled={siteMuted}
          excludeIds={[currentUser.id]}
          onSubmit={handleSend}
        />
        <button className="btn btn-primary" onClick={handleSend} disabled={siteMuted || !input.trim() || sending}>
          {sending ? "..." : "发送"}
        </button>
      </div>
    </>
  );
}
