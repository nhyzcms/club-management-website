import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Model } from "survey-core";
import { Survey } from "survey-react-ui";
import "survey-core/survey-core.css";
import { activityApi } from "../api/activities";
import type { ActivityDetail, SurveyResponsesPayload } from "../types/activities";
import AppShell from "../components/AppShell";
import { SURVEY_LOCALE } from "../utils/surveyLocale";
import "../styles/detail.css";
import "../styles/survey.css";

/** 检索输入 → 生效检索词的防抖间隔（ms）。 */
const SEARCH_DEBOUNCE_MS = 300;

/** 单份作答：display 模式（与 admin 查看作答同款）。 */
function ResponseDetail({
  schema, answers,
}: {
  schema: Record<string, unknown>;
  answers: Record<string, unknown>;
}) {
  const model = useMemo(() => {
    const m = new Model(schema);
    m.locale = SURVEY_LOCALE;
    m.mode = "display";
    m.questionsOnPageMode = "singlePage";
    m.showCompletedPage = false;
    m.widthMode = "responsive";
    m.data = answers;
    return m;
  }, [schema, answers]);
  return (
    <div className="survey-card">
      <Survey model={model} />
    </div>
  );
}

export default function SurveyResponsesPage() {
  const { id } = useParams<{ id: string }>();
  const activityId = Number(id);
  const navigate = useNavigate();
  const [activity, setActivity] = useState<ActivityDetail | null>(null);
  const [data, setData] = useState<SurveyResponsesPayload | null>(null);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  // 检索：输入框即时回显，query 防抖后生效（每次变更都重打 responses 端点，
  // 过滤与命中提示都由后端算——前端不重复实现一套匹配口径）
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (!activityId) return;
    let alive = true;
    activityApi.get(activityId)
      .then((a) => { if (alive) setActivity(a); })
      .catch((e: any) => { if (alive) setError(e?.message || "加载失败"); });
    return () => { alive = false; };
  }, [activityId]);

  useEffect(() => {
    if (!activityId) return;
    let alive = true;
    setSearching(true);
    activityApi.responses(activityId, query)
      .then((r) => {
        if (!alive) return;
        setData(r);
        setError("");
        setOpenId(null);
      })
      .catch((e: any) => { if (alive) setError(e?.message || "加载失败"); })
      .finally(() => { if (alive) setSearching(false); });
    return () => { alive = false; };
  }, [activityId, query]);

  if (error && !data) {
    return <AppShell><div className="container detail-container detail-body"><p className="empty-text">{error}</p></div></AppShell>;
  }
  if (!activity || !data) {
    return <AppShell><div className="container detail-container detail-body"><p className="empty-text">加载中…</p></div></AppShell>;
  }

  const hasQuery = data.query !== "";

  return (
    <AppShell>
      <div className="page-head">
        <div className="container detail-container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate(`/activity/${activityId}`); }}>{activity.title}</a>
            <span className="sep">/</span>
            <span>问卷结果</span>
          </nav>
          <div className="detail-head-row">
            <div className="detail-head-main">
              <h1 className="detail-title">问卷结果</h1>
            </div>
            <div className="detail-head-actions">
              <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/activity/${activityId}/survey-stats`)}>查看统计</button>
              <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/activity/${activityId}`)}>返回</button>
            </div>
          </div>
          <p className="detail-sub">
            {hasQuery
              ? `匹配 ${data.results.length} 份 / 共 ${data.total} 份作答。`
              : (data.is_manager ? `共 ${data.total} 份作答（你可见全部）。` : "你可见自己的作答。")}
          </p>
          <div className="survey-search">
            <div className="input-affix">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4-4" /></svg>
              <input
                className="input"
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索作答内容…"
                aria-label="搜索作答内容"
              />
              {searching && <span className="hint">搜索中…</span>}
            </div>
          </div>
          {error && (
            <div className="alert alert-danger" style={{ margin: "var(--s-3) 0" }}>
              <span>{error}</span>
            </div>
          )}
          {data.results.length === 0 ? (
            <div className="prop-empty">
              <p>{hasQuery ? "没有匹配的作答。" : "暂无作答。"}</p>
            </div>
          ) : (
            <div className="card card-pad">
              <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {data.results.map((row) => (
                  <li key={row.id} style={{ borderBottom: "1px solid var(--border, #eee)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, padding: "10px 0" }}>
                      <span>{row.user_label}</span>
                      <span className="muted" style={{ fontSize: 13 }}>{new Date(row.submitted_at).toLocaleString("zh-CN")}</span>
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => setOpenId(openId === row.id ? null : row.id)}
                      >
                        {openId === row.id ? "收起" : "查看作答"}
                      </button>
                    </div>
                    {row.matches.length > 0 && (
                      <div className="survey-matches">
                        {row.matches.map((m) => (
                          <span key={m.name} className="survey-match">
                            <b>{m.title}</b>：{m.snippet}
                          </span>
                        ))}
                      </div>
                    )}
                    {openId === row.id && (
                      <div style={{ paddingBottom: 12 }}>
                        <ResponseDetail schema={data.schema} answers={row.answers} />
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
