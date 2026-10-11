import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppShell from "../components/AppShell";
import RichTextEditor from "../components/RichTextEditor";
import DocxPreview from "../components/DocxPreview";
import ArticleToc from "../components/ArticleToc";
import { api } from "../api/client";
import { aboutApi, type AboutBlock, type AboutPageData } from "../api/about";
import { newsApi } from "../api/news";
import { PANORAMA_PAGE_URL } from "../constants";
import "../styles/detail.css";
import "../styles/about.css";

function isDocx(name: string, url: string | null) {
  const s = `${name} ${url || ""}`.toLowerCase();
  return s.includes(".docx");
}

const OPEN_DWELL_MS = 280;
const CLOSE_LINGER_MS = 520;

function finePointer() {
  return window.matchMedia("(hover: hover) and (pointer: fine)").matches;
}

export default function AboutPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState<AboutPageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [canEdit, setCanEdit] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [draftPanorama, setDraftPanorama] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [pinnedKey, setPinnedKey] = useState<string | null>(null);
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pinnedInit = useRef(false);

  const load = () => aboutApi.get().then(setPage);

  const clearHoverTimer = () => {
    if (hoverTimer.current) {
      clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
  };

  const onBlockEnter = (key: string) => {
    if (!finePointer()) return;
    clearHoverTimer();
    hoverTimer.current = setTimeout(() => setHoveredKey(key), OPEN_DWELL_MS);
  };

  const onBlockLeave = (key: string) => {
    if (!finePointer()) return;
    clearHoverTimer();
    hoverTimer.current = setTimeout(() => {
      setHoveredKey((current) => (current === key ? null : current));
    }, CLOSE_LINGER_MS);
  };

  useEffect(() => () => clearHoverTimer(), []);

  // 首次加载完成后默认展开第一块（访客第一眼即可看到正文）
  useEffect(() => {
    if (page && !pinnedInit.current) {
      pinnedInit.current = true;
      setPinnedKey((prev) => prev ?? page.blocks[0]?.key ?? null);
    }
  }, [page]);

  useEffect(() => {
    document.title = "关于我们 · 南汇一中传媒社";
    load().catch((e) => setError(e?.message || "加载失败")).finally(() => setLoading(false));
    api.me()
      .then((d: any) => setCanEdit(!!d.user?.permissions?.can_edit_about))
      .catch(() => setCanEdit(false));
    const hash = window.location.hash;
    if (hash.startsWith("#block-")) setPinnedKey(hash.slice("#block-".length));
  }, []);

  const startEdit = (block: AboutBlock) => {
    setDraftTitle(block.title);
    setDraftContent(block.content);
    setDraftPanorama(block.panorama_url || "");
    setSaveError("");
    setEditingKey(block.key);
    setPinnedKey(block.key);
  };

  const showBlock = (key: string) => {
    setPinnedKey(key);
    document.getElementById(`block-${key}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const handleSave = async (block: AboutBlock) => {
    setSaving(true);
    setSaveError("");
    try {
      await aboutApi.updateBlock(block.key, {
        title: draftTitle.trim() || block.title,
        content: draftContent,
        panorama_url: block.key === "campus-overview" ? draftPanorama.trim() : block.panorama_url,
      });
      await load();
      setEditingKey(null);
    } catch (e: any) {
      setSaveError(e?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const uploadDoc = async (block: AboutBlock, file: File) => {
    const fd = new FormData();
    fd.append("document", file);
    try {
      await aboutApi.updateBlock(block.key, fd);
      await load();
    } catch (e: any) {
      setSaveError(e?.message || "上传失败");
    }
  };

  const clearDoc = async (block: AboutBlock) => {
    const fd = new FormData();
    fd.append("clear_document", "true");
    await aboutApi.updateBlock(block.key, fd);
    await load();
  };

  if (loading) {
    return <AppShell><div className="container detail-container"><p className="empty-text">加载中…</p></div></AppShell>;
  }
  if (error && !page) {
    return <AppShell><div className="container detail-container"><div className="alert alert-danger">{error}</div></div></AppShell>;
  }

  const blocks = page?.blocks || [];

  return (
    <AppShell>
      <div className="page-head about-head">
        <div className="container detail-container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <span>关于我们</span>
          </nav>
          <h1 className="detail-title">关于我们</h1>
          <p className="section-sub">了解传媒社、南汇一中，以及这个网站本身。</p>
        </div>
      </div>

      <div className="container detail-container about-layout">
        <nav className="about-toc" aria-label="关于区块">
          {blocks.map((b) => (
            <a key={b.key} href={`#block-${b.key}`} onClick={(e) => {
              e.preventDefault();
              showBlock(b.key);
            }}>{b.title}</a>
          ))}
        </nav>

        <div className="about-blocks">
          {blocks.map((block) => {
            const editing = editingKey === block.key;
            const pinned = pinnedKey === block.key;
            const hovering = hoveredKey === block.key;
            return (
              <section
                key={block.key}
                id={`block-${block.key}`}
                className={"card about-block" + (pinned ? " is-open" : "") + (editing ? " is-editing" : "") + (hovering ? " is-hover" : "")}
                onMouseEnter={() => onBlockEnter(block.key)}
                onMouseLeave={() => onBlockLeave(block.key)}
              >
                <div className="about-block-head">
                  <h2 className="about-block-title">
                    <button
                      type="button"
                      className="about-block-toggle"
                      aria-expanded={pinned || editing || hovering}
                      onClick={() => setPinnedKey(pinned ? null : block.key)}
                    >
                      <span className="section-h">{block.title}</span>
                      <svg className="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
                    </button>
                  </h2>
                  {canEdit && !editing && (
                    <button className="btn btn-ghost btn-sm" onClick={() => startEdit(block)}>编辑</button>
                  )}
                </div>

                <div className="about-block-body">
                  <div className="about-block-inner detail-section">
                    {!editing ? (
                      <>
                        {block.content ? (
                          <>
                            <ArticleToc html={block.content} />
                            <RichTextEditor key={`read-${block.key}`} content={block.content} editable={false} />
                          </>
                        ) : (
                          <p className="empty-text">{canEdit ? "尚未填写内容，点击「编辑」开始。" : "内容即将上线。"}</p>
                        )}
                        {block.key === "campus-overview" && (
                          <p style={{ marginTop: "var(--s-4)" }}>
                            <a className="btn btn-primary" href={PANORAMA_PAGE_URL} target="_blank" rel="noopener noreferrer">
                              校园全景图
                            </a>
                          </p>
                        )}
                        {block.document_url && (
                          <div className="about-doc" style={{ marginTop: "var(--s-4)" }}>
                            {isDocx(block.document_name, block.document_url) ? (
                              <DocxPreview url={block.document_url} />
                            ) : (
                              <iframe className="about-pdf" title={block.document_name} src={block.document_url} />
                            )}
                            <p className="detail-sub">
                              <a href={block.document_url} download={block.document_name}>下载原件（{block.document_name}）</a>
                            </p>
                          </div>
                        )}
                      </>
                    ) : (
                      <>
                        <h3 className="section-h">标题</h3>
                        <input className="input" value={draftTitle} onChange={(e) => setDraftTitle(e.target.value)} style={{ width: "100%" }} />
                        <h3 className="section-h" style={{ marginTop: "var(--s-5)" }}>正文</h3>
                        <RichTextEditor
                          key={`edit-${block.key}`}
                          content={draftContent}
                          onChange={setDraftContent}
                          imageUpload={(f: File) => newsApi.uploadImage(f).then((d) => d.url)}
                          iframeEmbed
                          minHeight={320}
                        />
                        {block.key === "campus-overview" && (
                          <>
                            <h3 className="section-h" style={{ marginTop: "var(--s-5)" }}>校园全景图外链</h3>
                            <input className="input" value={draftPanorama} onChange={(e) => setDraftPanorama(e.target.value)} placeholder="https://…" style={{ width: "100%" }} />
                          </>
                        )}
                        <h3 className="section-h" style={{ marginTop: "var(--s-5)" }}>文档保真导入（PDF / .docx）</h3>
                        <input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                               onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadDoc(block, f); }} />
                        {block.document_url && (
                          <button className="btn btn-ghost btn-sm" type="button" onClick={() => clearDoc(block)}>移除文档</button>
                        )}
                        {saveError && <div className="alert alert-danger" style={{ marginTop: "var(--s-3)" }}>{saveError}</div>}
                        <div className="detail-row" style={{ marginTop: "var(--s-4)" }}>
                          <button className="btn btn-primary" onClick={() => handleSave(block)} disabled={saving}>{saving ? "保存中…" : "保存"}</button>
                          <button className="btn btn-ghost" onClick={() => setEditingKey(null)} disabled={saving}>取消</button>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </AppShell>
  );
}
