import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { recruitmentApi } from "../api/recruitment";
import SurveyFill from "../components/SurveyFill";
import MobileTabBar from "../components/MobileTabBar";
import "../styles/mobile.css";

/** 手机版自我介绍问卷（/m/join/form）：须先在加入页确认公告。 */
export default function MobileJoinFormPage() {
  const navigate = useNavigate();
  const [schema, setSchema] = useState<Record<string, unknown> | null>(null);
  const [done, setDone] = useState("");
  const [count, setCount] = useState(0);
  const [max, setMax] = useState(5);

  useEffect(() => {
    document.title = "自我介绍问卷 · 南汇一中传媒社";
    if (sessionStorage.getItem("join_notice_ack") !== "1") {
      navigate("/m/join", { replace: true });
      return;
    }
    recruitmentApi
      .landing()
      .then((d) => {
        setSchema(d.schema);
        setCount(d.responded_count ?? 0);
        setMax(d.max_submissions ?? 5);
      })
      .catch(() => {});
  }, [navigate]);

  const goBack = () => {
    const st = window.history.state as { idx?: number } | null;
    if (st && typeof st.idx === "number" && st.idx > 0) navigate(-1);
    else navigate("/m/join");
  };

  const capped = count >= max;

  return (
    <div className="m-app">
      <header className="m-topbar">
        <button className="m-back" onClick={goBack} aria-label="返回">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6" /></svg>
          返回
        </button>
      </header>

      <div className="m-detail">
        <h1 className="m-detail-title">自我介绍问卷</h1>

        {done ? (
          <section className="m-detail-sec">
            <h3>已提交</h3>
            <p className="m-hint">{done}</p>
            <p className="m-hint">
              {count >= max
                ? `你已提交 ${count} 次，达到上限（${max} 次）。`
                : `你已提交 ${count} 次，还可以再提交 ${max - count} 次。`}
            </p>
            <div className="m-actions-row">
              {count < max && (
                <button className="m-btn-ghost" onClick={() => window.location.reload()}>再填一份</button>
              )}
              <button className="m-btn-primary" onClick={() => navigate("/m")}>返回首页</button>
            </div>
          </section>
        ) : capped ? (
          <section className="m-detail-sec">
            <h3>已达上限</h3>
            <p className="m-hint">你已提交 {count} 次，达到上限（最多 {max} 次）。</p>
            <button className="m-btn-primary" onClick={() => navigate("/m")}>返回首页</button>
          </section>
        ) : schema ? (
          <section className="m-detail-sec">
            <h3>问卷</h3>
            {count > 0 && <p className="m-hint">你已提交过 {count} 次，还可提交 {max - count} 次。</p>}
            <SurveyFill
              schema={schema}
              onComplete={async (answers) => {
                const res = await recruitmentApi.submit(answers, true);
                sessionStorage.removeItem("join_notice_ack");
                setCount((c) => c + 1);
                setDone(res.message || "报名已提交");
              }}
            />
          </section>
        ) : (
          <p className="m-empty">加载中…</p>
        )}
      </div>

      <MobileTabBar />
    </div>
  );
}
