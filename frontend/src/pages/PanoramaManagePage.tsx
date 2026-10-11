/**
 * 校园全景图管理页（`/#/panorama/manage`）：导入 / 编辑 / 删除 / 重新切片。
 *
 * 访问门禁：仅持 `panorama.manage_panoramas`（前端能力键 `can_manage_panoramas`）者可用；
 * 这里只是 UI 预判，真正的门禁在服务端 `CanManagePanorama`（无权限会拿到 403）。
 */
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import AppShell from "../components/AppShell";
import { api } from "../api/client";
import { panoramaApi } from "../api/panorama";
import {
  PANORAMA_ACCEPT,
  PANORAMA_ORIGIN_LABELS,
  PANORAMA_STATUS_LABELS,
  type PanoramaEditable,
  type PanoramaListItem,
} from "../types/panorama";
import "../styles/panorama.css";

/** 状态徒标配色：ready 用既有 badge-success，failed 用本域自备的 badge-danger。 */
const statusBadge = (status: PanoramaListItem["status"]) => {
  if (status === "ready") return "badge badge-success";
  if (status === "failed") return "badge badge-danger";
  return "badge badge-ghost";
};

export default function PanoramaManagePage() {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [items, setItems] = useState<PanoramaListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyId, setBusyId] = useState(0);
  const [editingId, setEditingId] = useState(0);

  // 上传表单
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [order, setOrder] = useState("0");
  const [published, setPublished] = useState(true);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // 行内编辑草稿
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editOrder, setEditOrder] = useState("0");
  const [editYaw, setEditYaw] = useState("0");
  const [editPitch, setEditPitch] = useState("0");
  const [editFov, setEditFov] = useState("100");

  useEffect(() => {
    document.title = "管理校园全景图 · 传媒社";
  }, []);

  useEffect(() => {
    api
      .me()
      .then((d: any) => setAllowed(!!d.user?.permissions?.can_manage_panoramas))
      .catch(() => setAllowed(false));
  }, []);

  const reload = () => {
    setLoading(true);
    panoramaApi
      .listAll()
      .then((list) => {
        setItems(list);
        setError("");
      })
      .catch(() => setError("全景图列表加载失败，请稍后重试。"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (allowed) reload();
    else if (allowed === false) setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowed]);

  /** 把接口的 `detail` 文案透出来（比通用文案更有用，如「这不是一张可用的球面全景图…」）。 */
  const fail = (err: any, fallback: string) => {
    const detail = typeof err?.message === "string" ? err.message : "";
    setError(detail && detail !== "请求失败" ? detail : fallback);
  };

  const onUpload = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setNotice("");
    setError("");
    if (!file) {
      setError("请选择全景图文件（等距柱状 JPEG/PNG/WebP，或装着全景图的 zip）。");
      return;
    }
    if (!title.trim()) {
      setError("请填写标题。");
      return;
    }

    const form = new FormData();
    form.append("source", file);
    form.append("title", title.trim());
    form.append("description", description);
    form.append("order", String(Number.parseInt(order || "0", 10) || 0));
    form.append("is_published", published ? "true" : "false");

    setUploading(true);
    try {
      const created = await panoramaApi.create(form);
      if (created.status === "failed") {
        setNotice(
          `已导入「${created.title}」，但切片失败：${created.error || "原因未知"}。可点「重新切片」重试。`,
        );
      } else {
        setNotice(
          `已导入「${created.title}」：原图 ${created.width}×${created.height}，` +
            `切出 ${created.tile_levels.length} 级瓦片，可以浏览了。`,
        );
      }
      setFile(null);
      setTitle("");
      setDescription("");
      setOrder("0");
      setPublished(true);
      if (fileRef.current) fileRef.current.value = "";
      reload();
    } catch (err: any) {
      fail(err, "导入失败，请稍后重试。");
    } finally {
      setUploading(false);
    }
  };

  const startEdit = async (item: PanoramaListItem) => {
    setError("");
    setNotice("");
    try {
      const detail = await panoramaApi.get(item.id);
      setEditingId(item.id);
      setEditTitle(detail.title);
      setEditDescription(detail.description);
      setEditOrder(String(detail.order));
      setEditYaw(String(detail.initial_yaw));
      setEditPitch(String(detail.initial_pitch));
      setEditFov(String(detail.initial_fov));
    } catch {
      setError("读取该条目详情失败。");
    }
  };

  const saveEdit = async () => {
    if (!editingId) return;
    const payload: PanoramaEditable = {
      title: editTitle.trim(),
      description: editDescription,
      order: Number.parseInt(editOrder || "0", 10) || 0,
      initial_yaw: Number.parseFloat(editYaw) || 0,
      initial_pitch: Number.parseFloat(editPitch) || 0,
      initial_fov: Number.parseFloat(editFov) || 100,
    };
    setBusyId(editingId);
    setError("");
    try {
      await panoramaApi.update(editingId, payload);
      setEditingId(0);
      setNotice("已保存。");
      reload();
    } catch (err: any) {
      fail(err, "保存失败。");
    } finally {
      setBusyId(0);
    }
  };

  const togglePublished = async (item: PanoramaListItem) => {
    setBusyId(item.id);
    setError("");
    try {
      await panoramaApi.update(item.id, { is_published: !item.is_published });
      setNotice(item.is_published ? `已取消公开「${item.title}」。` : `已公开「${item.title}」。`);
      reload();
    } catch (err: any) {
      fail(err, "切换公开状态失败。");
    } finally {
      setBusyId(0);
    }
  };

  const reprocess = async (item: PanoramaListItem) => {
    setBusyId(item.id);
    setError("");
    setNotice("");
    try {
      const updated = await panoramaApi.reprocess(item.id);
      setNotice(
        updated.status === "ready"
          ? `「${updated.title}」已重新切片。`
          : `重新切片未成功：${updated.error || "原因未知"}`,
      );
      reload();
    } catch (err: any) {
      fail(err, "重新切片失败。");
    } finally {
      setBusyId(0);
    }
  };

  const remove = async (item: PanoramaListItem) => {
    // 删除会连同存档原图与瓦片一起回收，不可恢复 —— 因此要确认
    if (!window.confirm(`删除「${item.title}」？原图与瓦片会一并回收，且不可恢复。`)) return;
    setBusyId(item.id);
    setError("");
    try {
      await panoramaApi.remove(item.id);
      setNotice(`已删除「${item.title}」。`);
      reload();
    } catch (err: any) {
      fail(err, "删除失败。");
    } finally {
      setBusyId(0);
    }
  };

  if (allowed === false) {
    return (
      <AppShell>
        <div className="container">
          <div className="card card-pad" style={{ marginTop: "var(--s-5)" }}>
            <h1 style={{ fontSize: 20, marginBottom: 8 }}>管理校园全景图</h1>
            <p className="muted">
              仅持有「管理校园全景图」权限（panorama.manage_panoramas）的成员可进入。
              如需导入或编辑全景图，请联系信息组授予该权限。
            </p>
            <p style={{ marginTop: 12 }}>
              <Link className="btn btn-ghost" to="/panorama">去看全景图</Link>
            </p>
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <Link to="/panorama">校园全景</Link>
            <span className="sep">/</span>
            <span>管理</span>
          </nav>
          <div className="page-head-row">
            <div>
              <h1>管理校园全景图</h1>
              <p className="section-sub">
                支持 DJI Fly / DJI GO 4 合成的 2:1 球面全景图（自动读 XMP 适配初始视角），
                也支持装着全景图的 zip。导入后服务端会同步切片，大图需等几秒。
              </p>
            </div>
            <Link className="btn btn-ghost" to="/panorama">去看全景图</Link>
          </div>
        </div>
      </div>

      <div className="container">
        {error && <p className="pano-note pano-note-error">{error}</p>}
        {notice && <p className="pano-note pano-note-ok">{notice}</p>}

        <form className="card card-pad pano-form" onSubmit={onUpload}>
          <h2 className="pano-form-title">导入全景图</h2>
          <div className="pano-form-grid">
            <label className="pano-field pano-field-wide">
              <span>全景图文件（JPEG / PNG / WebP，或 zip）</span>
              <input
                ref={fileRef}
                className="input"
                type="file"
                accept={PANORAMA_ACCEPT}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <label className="pano-field">
              <span>标题（必填）</span>
              <input
                className="input"
                type="text"
                value={title}
                maxLength={200}
                placeholder="如：操场"
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            <label className="pano-field">
              <span>排序（小的在前）</span>
              <input
                className="input tnum"
                type="number"
                min={0}
                max={9999}
                value={order}
                onChange={(e) => setOrder(e.target.value)}
              />
            </label>
            <label className="pano-field pano-field-wide">
              <span>描述（可空）</span>
              <textarea
                className="input"
                rows={2}
                maxLength={2000}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            <label className="pano-check">
              <input
                type="checkbox"
                checked={published}
                onChange={(e) => setPublished(e.target.checked)}
              />
              <span>立即对公众公开</span>
            </label>
          </div>
          <div className="pano-form-actions">
            <button className="btn btn-primary" type="submit" disabled={uploading}>
              {uploading ? "正在上传并切片…" : "导入并切片"}
            </button>
            <span className="muted">
              上传上限与站点策略「同步上传单文件上限」一致；非 2:1 完整球面全景图会被拒绝。
            </span>
          </div>
        </form>

        <h2 className="pano-list-title">全部全景图（{items.length}）</h2>
        {loading ? (
          <p className="pano-note">加载中…</p>
        ) : items.length === 0 ? (
          <p className="pano-note">还没有全景图，用上面的表单导入第一张。</p>
        ) : (
          <div className="pano-list">
            {items.map((item) => (
              <div className="pano-card" key={item.id}>
                <div className="pano-card-art">
                  {item.thumb_url ? (
                    <img src={item.thumb_url} alt={item.title} width={800} height={400} loading="lazy" />
                  ) : (
                    <span className="pano-chip-ph" />
                  )}
                </div>

                <div className="pano-card-body">
                  <div className="pano-card-head">
                    <strong>{item.title}</strong>
                    <span className={statusBadge(item.status)}>
                      {PANORAMA_STATUS_LABELS[item.status] ?? item.status}
                    </span>
                    {!item.is_published && <span className="badge">未公开</span>}
                    <span className="badge">{PANORAMA_ORIGIN_LABELS[item.origin] ?? item.origin}</span>
                    {item.device_model && <span className="badge">{item.device_model}</span>}
                  </div>

                  <p className="pano-card-meta muted tnum">
                    #{item.id} · 排序 {item.order}
                    {item.width && item.height ? ` · ${item.width}×${item.height}` : ""}
                    {item.capture_heading !== null ? ` · 拍摄朝向 ${item.capture_heading}°` : ""}
                  </p>

                  {item.status === "failed" && (
                    <p className="pano-note pano-note-error">
                      切片失败：点「重新切片」可重试（不需重传原图）；若反复失败，请核对原图是否完整。
                    </p>
                  )}

                  {editingId === item.id ? (
                    <div className="pano-edit">
                      <label className="pano-field">
                        <span>标题</span>
                        <input
                          className="input"
                          value={editTitle}
                          maxLength={200}
                          onChange={(e) => setEditTitle(e.target.value)}
                        />
                      </label>
                      <label className="pano-field pano-field-wide">
                        <span>描述</span>
                        <textarea
                          className="input"
                          rows={2}
                          maxLength={2000}
                          value={editDescription}
                          onChange={(e) => setEditDescription(e.target.value)}
                        />
                      </label>
                      <label className="pano-field">
                        <span>排序</span>
                        <input
                          className="input tnum"
                          type="number"
                          min={0}
                          max={9999}
                          value={editOrder}
                          onChange={(e) => setEditOrder(e.target.value)}
                        />
                      </label>
                      <label className="pano-field">
                        <span>初始偏航角 yaw（度）</span>
                        <input
                          className="input tnum"
                          type="number"
                          step="0.1"
                          value={editYaw}
                          onChange={(e) => setEditYaw(e.target.value)}
                        />
                      </label>
                      <label className="pano-field">
                        <span>初始俯仰角 pitch（度）</span>
                        <input
                          className="input tnum"
                          type="number"
                          step="0.1"
                          value={editPitch}
                          onChange={(e) => setEditPitch(e.target.value)}
                        />
                      </label>
                      <label className="pano-field">
                        <span>初始视场角 fov（度）</span>
                        <input
                          className="input tnum"
                          type="number"
                          step="1"
                          min={30}
                          max={120}
                          value={editFov}
                          onChange={(e) => setEditFov(e.target.value)}
                        />
                      </label>
                      <div className="pano-card-actions">
                        <button
                          className="btn btn-primary"
                          type="button"
                          onClick={saveEdit}
                          disabled={busyId === item.id}
                        >
                          保存
                        </button>
                        <button
                          className="btn btn-ghost"
                          type="button"
                          onClick={() => setEditingId(0)}
                        >
                          取消
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="pano-card-actions">
                      <Link className="btn btn-ghost" to={`/panorama?id=${item.id}`}>浏览</Link>
                      <button
                        className="btn btn-ghost"
                        type="button"
                        onClick={() => startEdit(item)}
                        disabled={busyId === item.id}
                      >
                        编辑
                      </button>
                      <button
                        className="btn btn-ghost"
                        type="button"
                        onClick={() => togglePublished(item)}
                        disabled={busyId === item.id}
                      >
                        {item.is_published ? "取消公开" : "公开"}
                      </button>
                      <button
                        className="btn btn-ghost"
                        type="button"
                        onClick={() => reprocess(item)}
                        disabled={busyId === item.id}
                      >
                        重新切片
                      </button>
                      <button
                        className="btn btn-ghost pano-danger"
                        type="button"
                        onClick={() => remove(item)}
                        disabled={busyId === item.id}
                      >
                        删除
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
