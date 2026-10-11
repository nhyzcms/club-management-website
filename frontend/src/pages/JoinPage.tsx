import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppShell from "../components/AppShell";
import RichTextEditor from "../components/RichTextEditor";
import ArticleToc from "../components/ArticleToc";
import { api } from "../api/client";
import { recruitmentApi } from "../api/recruitment";
import { newsApi } from "../api/news";
import "../styles/detail.css";
import "../styles/form.css";

export default function JoinPage() {
  const navigate = useNavigate();
  const [content, setContent] = useState("");
  const [ack, setAck] = useState(false);
  const [canEdit, setCanEdit] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [rteKey, setRteKey] = useState(0);

  const applyNotice = (html: string) => {
    setContent(html);
    setDraft(html);
  };

  useEffect(() => {
    document.title = "加入社团 · 南汇一中传媒社";
    recruitmentApi.landing()
      .then((d) => applyNotice(d.notice.content || ""))
      .catch(() => {});
    api.me()
      .then((d: any) => setCanEdit(!!d.user?.permissions?.can_edit_about))
      .catch(() => setCanEdit(false));
  }, []);

  const startEdit = () => {
    setDraft(content);
    setSaveError("");
    setRteKey((k) => k + 1);
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    setSaveError("");
    try {
      const saved = await recruitmentApi.updateNotice(draft);
      applyNotice(saved.content || draft);
      setEditing(false);
    } catch (e: any) {
      setSaveError(e?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell>
      <div className="page-head page-head-gap">
        <div className="container detail-container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <span>加入社团</span>
          </nav>
          <div className="page-head-row">
            <h1>加入社团</h1>
            {canEdit && !editing && (
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn btn-ghost btn-sm" onClick={() => navigate("/join/editor")}>编辑问卷</button>
                <button className="btn btn-ghost btn-sm" type="button" onClick={startEdit}>编辑公告</button>
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="container detail-container page-body-gap">
        <div className="card card-pad">
          {!editing ? (
            content ? (
              <>
                <ArticleToc html={content} />
                <RichTextEditor key="n" content={content} editable={false} />
              </>
            ) : <p className="empty-text">招生公告即将发布。</p>
          ) : (
            <>
              <RichTextEditor
                key={`e-${rteKey}`}
                content={draft}
                onChange={setDraft}
                imageUpload={(f: File) => newsApi.uploadImage(f).then((d) => d.url)}
                minHeight={280}
              />
              {saveError && <div className="alert alert-danger" role="alert" style={{ marginTop: 12 }}>{saveError}</div>}
              <div className="form-actions" style={{ marginTop: 12 }}>
                <button className="btn btn-ghost" type="button" onClick={() => { setEditing(false); setSaveError(""); }}>取消</button>
                <button className="btn btn-primary" type="button" disabled={saving} onClick={save}>{saving ? "保存中…" : "保存"}</button>
              </div>
            </>
          )}
        </div>
        <label style={{ display: "flex", gap: 8, margin: "var(--s-5) 0", alignItems: "flex-start" }}>
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>我已阅读并知晓公告内容</span>
        </label>
        <button className="btn btn-primary btn-lg" disabled={!ack} onClick={() => {
          sessionStorage.setItem("join_notice_ack", "1");
          navigate("/join/form");
        }}>
          立即加入
        </button>
      </div>
    </AppShell>
  );
}
