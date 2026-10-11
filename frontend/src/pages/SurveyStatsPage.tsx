import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Model } from "survey-core";
import { Dashboard } from "survey-analytics";
import "survey-analytics/survey.analytics.min.css";
import { activityApi } from "../api/activities";
import type { ActivityDetail, SurveyResponsesPayload } from "../types/activities";
import AppShell from "../components/AppShell";
import { SURVEY_LOCALE } from "../utils/surveyLocale";
import "../styles/detail.css";
import "../styles/survey.css";

export default function SurveyStatsPage() {
  const { id } = useParams<{ id: string }>();
  const activityId = Number(id);
  const navigate = useNavigate();
  const [activity, setActivity] = useState<ActivityDetail | null>(null);
  const [data, setData] = useState<SurveyResponsesPayload | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!activityId) return;
    setLoading(true);
    Promise.all([activityApi.get(activityId), activityApi.responses(activityId)])
      .then(([a, r]) => { setActivity(a); setData(r); })
      .catch((e: any) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false));
  }, [activityId]);

  useEffect(() => {
    if (!data || !panelRef.current) return;
    const panel = panelRef.current;
    try {
      const survey = new Model(data.schema);
      survey.locale = SURVEY_LOCALE;
      const dashboard = new Dashboard({
        questions: survey.getAllQuestions(),
        data: data.results.map((r) => r.answers),
        allowHideQuestions: true,
      });
      dashboard.render(panel);
    } catch (e: any) {
      panel.textContent = "无法渲染统计：" + (e?.message || e);
    }
    return () => { panel.innerHTML = ""; };
  }, [data]);

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
            <span>问卷统计</span>
          </nav>
          <div className="detail-head-row">
            <div className="detail-head-main">
              <h1 className="detail-title">问卷统计</h1>
            </div>
            <div className="detail-head-actions">
              <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/activity/${activityId}/survey-responses`)}>查看结果</button>
              <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/activity/${activityId}`)}>返回</button>
            </div>
          </div>
          <p className="detail-sub">{`共 ${data.results.length} 份作答。`}</p>
          {data.results.length === 0 ? (
            <div className="prop-empty"><p>暂无作答，统计图将在有人作答后展示。</p></div>
          ) : (
            <div ref={panelRef} className="card card-pad" />
          )}
        </div>
      </div>
    </AppShell>
  );
}
