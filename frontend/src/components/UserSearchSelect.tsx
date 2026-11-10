import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import Avatar from "./Avatar";
import "./UserSearchSelect.css";

// 用户搜索选择器的最小用户形状（来自 /auth/users/ 与任务详情的 assignee/collaborators）
export interface SelectUser {
  id: number;
  username: string;
  nickname: string;
  avatar: string | null;
}

/**
 * 搜索式用户选择器（防抖输入即搜 /auth/users/?search=）。
 * - single：单选，已选用户以 chip 回显在输入框内（可 × 移除）；多选同理但可叠加多个。
 * - 结果下拉排除已选用户；点选即加入/切换。
 */
export default function UserSearchSelect({
  selected,
  onChange,
  single = false,
  placeholder = "搜索用户…",
  excludeIds = [],
}: {
  selected: SelectUser[];
  onChange: (users: SelectUser[]) => void;
  single?: boolean;
  placeholder?: string;
  excludeIds?: number[];
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SelectUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const skipKey = [...excludeIds, ...selected.map((s) => s.id)].join(",");

  // 防抖搜索：输入 300ms 后查询；已选用户与 excludeIds 从候选中剔除
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const skip = new Set(skipKey ? skipKey.split(",").map(Number) : []);
    const t = setTimeout(() => {
      api
        .searchUsers(query.trim())
        .then((d) => {
          if (cancelled) return;
          setResults((d.results || []).filter((u) => !skip.has(u.id)));
        })
        .catch(() => {
          if (cancelled) return;
          setResults([]);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [query, skipKey]);

  // 点击组件外部时收起下拉
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const pick = (u: SelectUser) => {
    if (single) onChange([u]);
    else onChange(selected.some((s) => s.id === u.id) ? selected.filter((s) => s.id !== u.id) : [...selected, u]);
    setQuery("");
    setOpen(false);
  };

  const remove = (id: number) => onChange(selected.filter((s) => s.id !== id));

  const displayName = (u: SelectUser) => u.nickname || u.username;

  return (
    <div className="user-search" ref={rootRef}>
      <div className="user-search-input">
        {selected.map((u) => (
          <span key={u.id} className="user-chip">
            <Avatar user={u} />
            {displayName(u)}
            <button type="button" aria-label={`移除 ${displayName(u)}`} onClick={() => remove(u.id)}>×</button>
          </span>
        ))}
        <input
          type="search"
          value={query}
          placeholder={selected.length === 0 ? placeholder : ""}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
          }}
        />
        {loading && <span className="user-search-loading">…</span>}
      </div>

      {open && (
        <div className="user-search-menu">
          {results.length === 0 ? (
            <div className="user-search-empty">{loading ? "搜索中…" : "无匹配用户"}</div>
          ) : (
            results.map((u) => (
              <button key={u.id} type="button" className="user-search-option" onClick={() => pick(u)}>
                <Avatar user={u} />
                <span className="user-search-name">{displayName(u)}</span>
                <span className="user-search-uname">@{u.username}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
