import { useCallback, useEffect, useState } from "react";
import Pagination from "../../Pagination";
import {
  POSTCARD_GRADES,
  POSTCARD_REGIONS,
  REG_STATUS_OPTIONS,
  downloadWithCredentials,
  postcardAdminApi,
  type Paged,
  type RecordQuery,
  type RecordRow,
} from "../../../api/postcardAdmin";
import { errMessage, fmtTime, isForbidden } from "./pure";

/** 登记记录：搜索 / 筛选 / 改 / 取消 / 删 / 导出（Excel 或 PDF）。 */
export default function RecordsTab() {
  const emptyFilters: RecordQuery = { q: "", grade: "", class_no: "", region: "", school: "", status: "" };
  const [draft, setDraft] = useState<RecordQuery>(emptyFilters);
  const [filters, setFilters] = useState<RecordQuery>(emptyFilters);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Paged<RecordRow> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<RecordRow | null>(null);
  const [form, setForm] = useState({
    sender_name: "",
    grade: "g1",
    class_no: 1,
    dest_region: POSTCARD_REGIONS[0],
    dest_school: "",
    status: "registered",
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await postcardAdminApi.records({ ...filters, page }));
    } catch (e) {
      setError(isForbidden(e) ? "需要 manage_postcard 权限。" : errMessage(e));
    } finally {
      setLoading(false);
    }
  }, [filters, page]);

  useEffect(() => {
    void load();
  }, [load]);

  /** 查询按钮：草稿条件生效（输入过程中不发请求，避免每敲一个字打一次接口）。 */
  const search = () => {
    setPage(1);
    setFilters({ ...draft });
  };

  const openEdit = (row: RecordRow) => {
    setEditing(row);
    setForm({
      sender_name: row.registration.sender_name,
      grade: row.registration.grade,
      class_no: row.registration.class_no,
      dest_region: row.registration.dest_region,
      dest_school: row.registration.dest_school,
      status: row.registration.status,
    });
  };

  const saveEdit = async () => {
    if (!editing) return;
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await postcardAdminApi.updateRegistration(editing.registration.reg_code, form);
      setEditing(null);
      setNotice("登记单已更新。");
      await load();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const cancelReg = async (row: RecordRow) => {
    if (!window.confirm(`取消登记单 ${row.registration.reg_code} 的全部明信片？`)) return;
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await postcardAdminApi.updateRegistration(row.registration.reg_code, { status: "cancelled" });
      setNotice("登记单已取消。");
      await load();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const removeReg = async (row: RecordRow) => {
    if (!window.confirm(`彻底删除登记单 ${row.registration.reg_code}？照片文件一并删除，不可恢复。`)) return;
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await postcardAdminApi.deleteRegistration(row.registration.reg_code);
      setNotice("登记单已删除。");
      await load();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const exportAs = async (fmt: "xlsx" | "pdf") => {
    setError("");
    setBusy(true);
    // 导出用「当前已生效」的条件，和屏幕上的表格一致。
    try {
      await downloadWithCredentials(
        postcardAdminApi.exportUrl(filters, fmt),
        `明信片登记-${new Date().toISOString().slice(0, 10)}.${fmt}`,
      );
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const totalPages = data ? Math.max(1, Math.ceil(data.count / 20)) : 1;

  return (
    <div className="pa-stack">
      {error && <p className="pa-error">{error}</p>}
      {notice && <p className="pa-ok">{notice}</p>}

      <section className="pa-card">
        <div className="pa-filters">
          <input
            placeholder="姓名 / 登记码 / 条码"
            value={draft.q || ""}
            onChange={(e) => setDraft((f) => ({ ...f, q: e.target.value }))}
            onKeyDown={(e) => {
              if (e.key === "Enter") search();
            }}
          />
          <select value={draft.grade || ""} onChange={(e) => setDraft((f) => ({ ...f, grade: e.target.value }))}>
            <option value="">全部年级</option>
            {POSTCARD_GRADES.map((g) => (
              <option key={g.value} value={g.value}>
                {g.label}
              </option>
            ))}
          </select>
          <select
            value={draft.class_no || ""}
            onChange={(e) => setDraft((f) => ({ ...f, class_no: e.target.value }))}
          >
            <option value="">全部班级</option>
            {Array.from({ length: 8 }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n}班
              </option>
            ))}
          </select>
          <select value={draft.region || ""} onChange={(e) => setDraft((f) => ({ ...f, region: e.target.value }))}>
            <option value="">全部区</option>
            {POSTCARD_REGIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <input
            placeholder="寄达校"
            value={draft.school || ""}
            onChange={(e) => setDraft((f) => ({ ...f, school: e.target.value }))}
          />
          <select value={draft.status || ""} onChange={(e) => setDraft((f) => ({ ...f, status: e.target.value }))}>
            <option value="">全部状态</option>
            {REG_STATUS_OPTIONS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <button type="button" className="btn btn-secondary btn-sm" onClick={search}>
            查询
          </button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void exportAs("xlsx")}>
            导出 Excel
          </button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void exportAs("pdf")}>
            导出 PDF
          </button>
        </div>
        <p className="pa-hint">共 {data?.count ?? 0} 张明信片（按条目平铺，同一登记单可能多行）。导出会带上当前筛选条件。</p>
      </section>

      {editing && (
        <section className="pa-card pa-editor">
          <h3 className="pa-card-title">编辑登记单 {editing.registration.reg_code}</h3>
          <div className="pa-grid2">
            <label className="pa-field">
              <span>寄出人姓名</span>
              <input
                value={form.sender_name}
                onChange={(e) => setForm((f) => ({ ...f, sender_name: e.target.value }))}
              />
            </label>
            <label className="pa-field">
              <span>年级</span>
              <select value={form.grade} onChange={(e) => setForm((f) => ({ ...f, grade: e.target.value }))}>
                {POSTCARD_GRADES.map((g) => (
                  <option key={g.value} value={g.value}>
                    {g.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="pa-field">
              <span>班级</span>
              <select
                value={form.class_no}
                onChange={(e) => setForm((f) => ({ ...f, class_no: Number(e.target.value) }))}
              >
                {Array.from({ length: 8 }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>
                    {n}班
                  </option>
                ))}
              </select>
            </label>
            <label className="pa-field">
              <span>寄达区</span>
              <select
                value={form.dest_region}
                onChange={(e) => setForm((f) => ({ ...f, dest_region: e.target.value }))}
              >
                {POSTCARD_REGIONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <label className="pa-field">
              <span>寄达校</span>
              <input
                value={form.dest_school}
                onChange={(e) => setForm((f) => ({ ...f, dest_school: e.target.value }))}
              />
            </label>
            <label className="pa-field">
              <span>状态</span>
              <select value={form.status} onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
                {REG_STATUS_OPTIONS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="pa-actions">
            <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void saveEdit()}>
              保存
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>
              取消
            </button>
          </div>
        </section>
      )}

      <div className="pa-table-wrap">
        <table className="pa-table">
          <thead>
            <tr>
              <th>条码</th>
              <th>寄出人</th>
              <th>年级班级</th>
              <th>寄达</th>
              <th>状态</th>
              <th>登记时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {loading && !data && (
              <tr>
                <td colSpan={7} className="pa-muted">
                  加载中…
                </td>
              </tr>
            )}
            {(data?.results ?? []).map((row) => (
              <tr key={row.item_id}>
                <td className="tnum">{row.barcode}</td>
                <td>{row.registration.sender_name}</td>
                <td>
                  {row.registration.grade_label}
                  {row.registration.class_no}班
                </td>
                <td>
                  {row.registration.dest_region} {row.registration.dest_school}
                </td>
                <td>
                  {row.registration.status_label} / {row.item_status_label}
                </td>
                <td>{fmtTime(row.registration.created_at)}</td>
                <td className="pa-row-actions">
                  <button type="button" className="pa-link" onClick={() => openEdit(row)}>
                    编辑
                  </button>
                  <button
                    type="button"
                    className="pa-link"
                    disabled={row.registration.status === "cancelled"}
                    onClick={() => void cancelReg(row)}
                  >
                    取消
                  </button>
                  <button type="button" className="pa-link-danger" onClick={() => void removeReg(row)}>
                    删除
                  </button>
                </td>
              </tr>
            ))}
            {data && data.results.length === 0 && (
              <tr>
                <td colSpan={7} className="pa-muted">
                  没有符合条件的记录。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <Pagination page={page} totalPages={totalPages} onChange={setPage} />
    </div>
  );
}
