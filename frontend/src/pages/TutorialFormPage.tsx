import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppShell from "../components/AppShell";
import { tutorialApi } from "../api/tutorials";
import "../styles/form.css";
import "../styles/list.css";
import "../styles/detail.css";

export default function TutorialFormPage() {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [cover, setCover] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    document.title = "上传教程";
  }, []);

  const submit = async () => {
    if (!file || !title.trim()) return;
    setSaving(true);
    setError("");
    const fd = new FormData();
    fd.append("title", title.trim());
    fd.append("description", description);
    fd.append("file", file);
    if (cover) fd.append("cover", cover);
    try {
      const created = await tutorialApi.create(fd);
      navigate(`/tutorials/${created.id}`);
    } catch (e: any) {
      setError(e?.message || "上传失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell>
      <div className="page-head page-head-gap">
        <div className="container detail-container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/tutorials"); }}>教程集锦</a>
            <span className="sep">/</span>
            <span>上传</span>
          </nav>
          <h1>上传教程</h1>
        </div>
      </div>
      <div className="container detail-container page-body-gap">
        <div className="card card-pad form-card">
          <div className="form-stack">
            <label className="field"><span className="label">标题</span>
              <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
            </label>
            <label className="field"><span className="label">描述</span>
              <textarea className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} rows={4} />
            </label>
            <label className="field"><span className="label">视频或文档</span>
              <input type="file" accept="video/mp4,video/webm,.mp4,.webm,.pdf,.docx,application/pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </label>
            <label className="field"><span className="label">封面（可选）</span>
              <input type="file" accept="image/*" onChange={(e) => setCover(e.target.files?.[0] || null)} />
            </label>
            {error && <div className="alert alert-danger">{error}</div>}
            <div className="form-actions">
              <button className="btn btn-ghost" type="button" onClick={() => navigate("/tutorials")}>取消</button>
              <button className="btn btn-primary" disabled={saving || !file || !title.trim()} onClick={submit}>
                {saving ? "上传中…" : "提交"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
