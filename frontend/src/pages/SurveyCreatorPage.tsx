import { useEffect, useRef, useState, type ReactNode } from "react";
import { SurveyCreator, SurveyCreatorComponent } from "survey-creator-react";
import "survey-core/survey-core.css";
import "survey-creator-core/survey-creator-core.css";
import { SURVEY_LOCALE } from "../utils/surveyCreatorLocale";
import AppShell from "../components/AppShell";
import "../styles/detail.css";
import "../styles/form.css";

const EMPTY_SCHEMA: Record<string, unknown> = {
  title: "",
  pages: [{ name: "page1", elements: [] }],
};

export default function SurveyCreatorPage({
  load,
  save,
  canSave,
  title,
  children,
}: {
  load: () => Promise<Record<string, unknown>>;
  save: (schema: Record<string, unknown>) => Promise<void>;
  canSave: boolean;
  title: string;
  children?: ReactNode;
}) {
  const [creator, setCreator] = useState<SurveyCreator | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const saveRef = useRef(save);
  saveRef.current = save;

  useEffect(() => {
    document.title = title;
  }, [title]);

  useEffect(() => {
    let alive = true;
    setCreator(null);
    setError("");
    setMsg("");
    load()
      .then((schema) => {
        if (!alive) return;
        const c = new SurveyCreator({ showLogicTab: true, locale: SURVEY_LOCALE });
        c.JSON = schema || EMPTY_SCHEMA;
        // Creator 工具栏「保存」默认只提示本地已保存；接到后端才算真正落库。
        c.saveSurveyFunc = (saveNo: number, callback: (no: number, success: boolean) => void) => {
          saveRef.current(c.JSON as Record<string, unknown>)
            .then(() => {
              if (!alive) return;
              setMsg("已保存");
              setError("");
              callback(saveNo, true);
            })
            .catch((err: unknown) => {
              if (!alive) return;
              setError(err instanceof Error ? err.message : "保存失败");
              callback(saveNo, false);
            });
        };
        setCreator(c);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "加载失败");
      });
    return () => {
      alive = false;
    };
  }, [load]);

  const onSave = async () => {
    if (!creator) return;
    setError("");
    try {
      await saveRef.current(creator.JSON as Record<string, unknown>);
      setMsg("已保存");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "保存失败");
    }
  };

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          {children}
          <div className="page-head-row">
            <h1>{title}</h1>
            {canSave && creator && (
              <button className="btn btn-primary" onClick={() => void onSave()}>保存 Schema</button>
            )}
          </div>
          {msg && <p className="detail-sub">{msg}</p>}
        </div>
      </div>
      <div className="container">
        {error && <div className="alert alert-danger" style={{ margin: "var(--s-4) 0" }}><span>{error}</span></div>}
        {!canSave && creator && (
          <div className="alert alert-danger" style={{ margin: "var(--s-4) 0" }}>
            <span>问卷已锁定，无法保存。</span>
          </div>
        )}
        {creator && (
          <div style={{ height: "70vh", minHeight: 480 }}>
            <SurveyCreatorComponent creator={creator} />
          </div>
        )}
        {!creator && !error && <p className="empty-text">加载中…</p>}
      </div>
    </AppShell>
  );
}
