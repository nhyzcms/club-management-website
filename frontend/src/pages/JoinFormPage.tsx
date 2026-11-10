import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppShell from "../components/AppShell";
import SurveyFill from "../components/SurveyFill";
import { recruitmentApi } from "../api/recruitment";
import "../styles/detail.css";

export default function JoinFormPage() {
  const navigate = useNavigate();
  const [schema, setSchema] = useState<Record<string, unknown> | null>(null);
  const [done, setDone] = useState("");
  const [count, setCount] = useState(0);
  const [max, setMax] = useState(5);

  useEffect(() => {
    document.title = "自我介绍问卷";
    if (sessionStorage.getItem("join_notice_ack") !== "1") {
      navigate("/join", { replace: true });
      return;
    }
    recruitmentApi.landing().then((d) => {
      setSchema(d.schema);
      setCount(d.responded_count ?? 0);
      setMax(d.max_submissions ?? 5);
    });
  }, [navigate]);

  const capped = count >= max;

  return (
    <AppShell>
      <div className="page-head page-head-gap">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/join"); }}>加入社团</a>
            <span className="sep">/</span>
            <span>自我介绍问卷</span>
          </nav>
          <h1>自我介绍问卷</h1>
        </div>
      </div>
      <div className="container page-body-gap">
        {done ? (
          <div className="card card-pad">
            <p>{done}</p>
            <p className="muted" style={{ marginTop: 8 }}>
              {count >= max
                ? `你已提交 ${count} 次，达到上限（${max} 次）。`
                : `你已提交 ${count} 次，还可以再提交 ${max - count} 次。`}
            </p>
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              {count < max && (
                <button className="btn btn-ghost" onClick={() => window.location.reload()}>再填一份</button>
              )}
              <button className="btn btn-primary" onClick={() => navigate("/")}>返回首页</button>
            </div>
          </div>
        ) : capped ? (
          <div className="card card-pad">
            <p>你已提交 {count} 次，达到上限（最多 {max} 次）。</p>
            <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={() => navigate("/")}>返回首页</button>
          </div>
        ) : schema ? (
          <div className="card card-pad">
            {count > 0 && (
              <p className="muted" style={{ marginBottom: 12 }}>
                你已提交过 {count} 次，还可提交 {max - count} 次。
              </p>
            )}
            <SurveyFill
              schema={schema}
              onComplete={async (answers) => {
                const res = await recruitmentApi.submit(answers, true);
                sessionStorage.removeItem("join_notice_ack");
                setCount((c) => c + 1);
                setDone(res.message || "报名已提交");
              }}
            />
          </div>
        ) : (
          <p className="empty-text">加载中…</p>
        )}
      </div>
    </AppShell>
  );
}
