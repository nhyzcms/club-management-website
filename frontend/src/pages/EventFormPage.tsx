import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppShell from "../components/AppShell";
import { eventApi } from "../api/events";
import type { EventVisibility } from "../types/events";
import "../styles/list.css";

const toIso = (value: string): string | null =>
  value ? new Date(value).toISOString() : null;

export default function EventFormPage() {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [body, setBody] = useState("");
  const [startAt, setStartAt] = useState("");
  const [endAt, setEndAt] = useState("");
  const [visibility, setVisibility] = useState<EventVisibility>("members");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    document.title = "发起活动 · 南汇一中传媒社";
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!startAt) {
      setError("请填写开始时间");
      return;
    }
    if (endAt && new Date(endAt) <= new Date(startAt)) {
      setError("结束时间必须晚于开始时间");
      return;
    }
    setSubmitting(true);
    try {
      await eventApi.create({
        title,
        summary,
        body,
        start_at: toIso(startAt)!,
        end_at: toIso(endAt),
        visibility,
      });
      navigate("/events");
    } catch (err: any) {
      setError(err?.message || "创建失败，请稍后再试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/events"); }}>活动</a>
            <span className="sep">/</span>
            <span>发起</span>
          </nav>
          <h1>发起活动</h1>
          <p className="section-sub">创建后为草稿，确认无误再发布。到结束时间自动关闭。</p>
        </div>
      </div>

      <div className="container" style={{ paddingBottom: "var(--s-16)", maxWidth: 720 }}>
        {error && <div className="alert alert-danger" style={{ marginBottom: "var(--s-4)" }}>{error}</div>}
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="ev-title">标题</label>
            <input id="ev-title" className="input" value={title} required maxLength={200}
              onChange={(e) => setTitle(e.target.value)} />
          </div>

          <div className="field">
            <label htmlFor="ev-summary">简介</label>
            <input id="ev-summary" className="input" value={summary} maxLength={300}
              onChange={(e) => setSummary(e.target.value)} />
          </div>

          <div className="field">
            <label htmlFor="ev-start">开始时间</label>
            <input id="ev-start" className="input" type="datetime-local" value={startAt} required
              onChange={(e) => setStartAt(e.target.value)} />
          </div>

          <div className="field">
            <label htmlFor="ev-end">结束时间（留空则不自动关闭）</label>
            <input id="ev-end" className="input" type="datetime-local" value={endAt}
              onChange={(e) => setEndAt(e.target.value)} />
          </div>

          <div className="field">
            <label htmlFor="ev-visibility">可见范围</label>
            <select id="ev-visibility" className="input" value={visibility}
              onChange={(e) => setVisibility(e.target.value as EventVisibility)}>
              <option value="members">仅成员</option>
              <option value="public">公开</option>
            </select>
          </div>

          <div className="field">
            <label htmlFor="ev-body">正文（支持 HTML）</label>
            <textarea id="ev-body" className="input" rows={10} value={body}
              onChange={(e) => setBody(e.target.value)} />
          </div>

          <div style={{ display: "flex", gap: 12, marginTop: "var(--s-6)" }}>
            <button className="btn btn-primary" type="submit" disabled={submitting}>
              {submitting ? "保存中…" : "保存草稿"}
            </button>
            <button className="btn btn-ghost" type="button" onClick={() => navigate("/events")}>
              取消
            </button>
          </div>
        </form>
      </div>
    </AppShell>
  );
}
