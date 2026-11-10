import { useEffect, useMemo, useRef, useState } from "react";
import type { Paginated } from "../types/pagination";

/**
 * 列表分页钩子：封装「当前页数据 + 页码 + 总页数」的获取与切换。
 *
 * - filters 变化（内容不同）时自动重置回第 1 页；page 变化时重新拉取。
 * - refetch() 强制重拉当前页（如变更后需要刷新，例如列表外操作后）。
 * - enabled=false 时不发起请求（如等待身份解析后再拉）；error 暴露加载失败供页面提示。
 * - 返回 { data, count, page, setPage, totalPages, loading, error, refetch }。
 */
export function usePagedList<T>(
  fetcher: (params: Record<string, string>) => Promise<Paginated<T>>,
  pageSize: number,
  filters: Record<string, string | undefined> = {},
  enabled = true,
) {
  const [data, setData] = useState<T[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(!enabled);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const filterKey = useMemo(() => JSON.stringify(filters), [filters]);

  // fetcher 经 ref 调用：调用方常传内联箭头，直接进 deps 会随渲染换身份导致重复请求
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  // 筛选/搜索变化 → 回到第 1 页（并清掉旧的错误提示）
  useEffect(() => {
    setPage(1);
    setError(null);
  }, [filterKey]);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const params: Record<string, string> = { page: String(page) };
    for (const [k, v] of Object.entries(filters)) {
      if (v) params[k] = v;
    }
    fetcherRef.current(params)
      .then((d) => {
        if (cancelled) return;
        setData(d.results || []);
        setCount(typeof d.count === "number" ? d.count : 0);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setData([]);
        setCount(0);
        setError(e?.message || "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [page, filterKey, reloadKey, enabled]);

  const totalPages = Math.max(1, Math.ceil(count / pageSize));

  return {
    data,
    count,
    page,
    setPage,
    totalPages,
    loading,
    error,
    refetch: () => setReloadKey((k) => k + 1),
  };
}
