import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode, type TextareaHTMLAttributes, type InputHTMLAttributes } from "react";
import { api } from "../api/client";
import Avatar from "./Avatar";
import type { SelectUser } from "./UserSearchSelect";
import "./UserSearchSelect.css";

export function highlightMentions(text: string): ReactNode {
  const parts = text.split(/(@\w+)/g);
  return parts.map((p, i) => (
    p.startsWith("@") ? <span key={i} className="comment-mention">{p}</span> : <span key={i}>{p}</span>
  ));
}

/** `@` 后到光标的片段：须顶格或跟在空白后，与后端 `@(\w+)` 对齐。 */
function mentionAt(text: string, caret: number): { start: number; query: string } | null {
  const before = text.slice(0, caret);
  const m = before.match(/(^|[\s])@(\w*)$/);
  if (!m) return null;
  const query = m[2];
  return { start: caret - query.length - 1, query };
}

type Common = {
  value: string;
  onChange: (value: string) => void;
  excludeIds?: number[];
  disabled?: boolean;
  placeholder?: string;
  className?: string;
};

function MentionMenu({
  results,
  loading,
  active,
  onPick,
}: {
  results: SelectUser[];
  loading: boolean;
  active: number;
  onPick: (u: SelectUser) => void;
}) {
  return (
    <div className="user-search-menu mention-menu" role="listbox">
      {results.length === 0 ? (
        <div className="user-search-empty">{loading ? "搜索中…" : "无匹配用户"}</div>
      ) : (
        results.map((u, i) => (
          <button
            key={u.id}
            type="button"
            role="option"
            aria-selected={i === active}
            className={"user-search-option" + (i === active ? " is-active" : "")}
            onMouseDown={(e) => { e.preventDefault(); onPick(u); }}
          >
            <Avatar user={u} />
            <span className="user-search-name">{u.nickname || u.username}</span>
            <span className="user-search-uname">@{u.username}</span>
          </button>
        ))
      )}
    </div>
  );
}

function useMentionSearch(
  value: string,
  caret: number,
  excludeIds: number[],
  enabled: boolean,
  dismissedStart: number | null,
) {
  const raw = enabled ? mentionAt(value, caret) : null;
  const token = raw && raw.start !== dismissedStart ? raw : null;
  const [results, setResults] = useState<SelectUser[]>([]);
  const [loading, setLoading] = useState(false);
  const skipKey = excludeIds.join(",");

  useEffect(() => {
    if (!token) {
      setResults([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const skip = new Set(skipKey ? skipKey.split(",").map(Number) : []);
    const t = window.setTimeout(() => {
      api.searchUsers(token.query)
        .then((d) => {
          if (cancelled) return;
          setResults((d.results || []).filter((u) => !skip.has(u.id)));
        })
        .catch(() => { if (!cancelled) setResults([]); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [token?.query, token?.start, skipKey]); // eslint-disable-line react-hooks/exhaustive-deps

  return { token, results, loading };
}

export function MentionTextarea({
  value,
  onChange,
  excludeIds = [],
  disabled,
  placeholder,
  className = "textarea",
  rows = 3,
  ...rest
}: Common & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange">) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [caret, setCaret] = useState(0);
  const [active, setActive] = useState(0);
  const [dismissedStart, setDismissedStart] = useState<number | null>(null);
  const { token, results, loading } = useMentionSearch(value, caret, excludeIds, !disabled, dismissedStart);
  const open = !!token && !disabled;

  useEffect(() => { setActive(0); }, [token?.query, token?.start]);

  const pick = (u: SelectUser) => {
    if (!token) return;
    const next = `${value.slice(0, token.start)}@${u.username} ${value.slice(caret)}`;
    const pos = token.start + u.username.length + 2;
    setDismissedStart(null);
    onChange(next);
    requestAnimationFrame(() => {
      const el = ref.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(pos, pos);
      setCaret(pos);
    });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (open && results.length) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((i) => (i + 1) % results.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((i) => (i - 1 + results.length) % results.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        pick(results[active] || results[0]);
        return;
      }
    }
    if (e.key === "Escape" && token) {
      e.preventDefault();
      setDismissedStart(token.start);
      return;
    }
    rest.onKeyDown?.(e);
  };

  return (
    <div className="mention-wrap">
      {open && (
        <MentionMenu results={results} loading={loading} active={active} onPick={pick} />
      )}
      <textarea
        {...rest}
        ref={ref}
        className={className}
        value={value}
        rows={rows}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => {
          setDismissedStart(null);
          onChange(e.target.value);
          setCaret(e.target.selectionStart ?? e.target.value.length);
        }}
        onSelect={(e) => setCaret((e.target as HTMLTextAreaElement).selectionStart ?? 0)}
        onClick={(e) => setCaret((e.target as HTMLTextAreaElement).selectionStart ?? 0)}
        onKeyUp={(e) => setCaret((e.target as HTMLTextAreaElement).selectionStart ?? 0)}
        onKeyDown={onKeyDown}
      />
    </div>
  );
}

export function MentionInput({
  value,
  onChange,
  excludeIds = [],
  disabled,
  placeholder,
  className = "input",
  onSubmit,
  ...rest
}: Common & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & { onSubmit?: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [caret, setCaret] = useState(0);
  const [active, setActive] = useState(0);
  const [dismissedStart, setDismissedStart] = useState<number | null>(null);
  const { token, results, loading } = useMentionSearch(value, caret, excludeIds, !disabled, dismissedStart);
  const open = !!token && !disabled;

  useEffect(() => { setActive(0); }, [token?.query, token?.start]);

  const pick = (u: SelectUser) => {
    if (!token) return;
    const next = `${value.slice(0, token.start)}@${u.username} ${value.slice(caret)}`;
    const pos = token.start + u.username.length + 2;
    setDismissedStart(null);
    onChange(next);
    requestAnimationFrame(() => {
      const el = ref.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(pos, pos);
      setCaret(pos);
    });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (open && results.length) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((i) => (i + 1) % results.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((i) => (i - 1 + results.length) % results.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        pick(results[active] || results[0]);
        return;
      }
    }
    if (e.key === "Escape" && token) {
      e.preventDefault();
      setDismissedStart(token.start);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSubmit?.();
      return;
    }
    rest.onKeyDown?.(e);
  };

  return (
    <div className="mention-wrap">
      {open && (
        <MentionMenu results={results} loading={loading} active={active} onPick={pick} />
      )}
      <input
        {...rest}
        ref={ref}
        className={className}
        type="text"
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => {
          setDismissedStart(null);
          onChange(e.target.value);
          setCaret(e.target.selectionStart ?? e.target.value.length);
        }}
        onSelect={(e) => setCaret((e.target as HTMLInputElement).selectionStart ?? 0)}
        onClick={(e) => setCaret((e.target as HTMLInputElement).selectionStart ?? 0)}
        onKeyUp={(e) => setCaret((e.target as HTMLInputElement).selectionStart ?? 0)}
        onKeyDown={onKeyDown}
      />
    </div>
  );
}
