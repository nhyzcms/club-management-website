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
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<number | null>(null);

  useEffect(() => {
    if (!activityId) return;
    setLoading(true);
    Promise.all([activityApi.get(activityId), activityApi.responses(activityId)])
      .then(([a, r]) => { setActivity(a); setData(r); })
      .catch((e: any) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false));
  }, [activityId]);

  if (loading) {
    return <AppShell><div className="container detail-container detail-body"><p className="empty-text">加载中…</p></div></AppShell>;
  }
  if (error || !data || !activity) {
    return <AppShell><div className="container detail-container detail-body"><p className="empty-text">{error || "加载失败"}</p></div></AppShell>;
  }

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
            {data.is_manager ? `共 ${data.results.length} 份作答（你可见全部）。` : "你可见自己的作答。"}
          </p>
          {data.results.length === 0 ? (
            <div className="prop-empty"><p>暂无作答。</p></div>
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
