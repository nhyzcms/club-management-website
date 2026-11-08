import { useCallback, useEffect, useMemo, useState } from "react";
import RichTextEditor from "../../RichTextEditor";
import {
  POSTCARD_GRADES,
  POSTCARD_REGIONS,
  postcardAdminApi,
  type AdminSchool,
} from "../../../api/postcardAdmin";
import { errMessage, groupSchools, isForbidden, isoToLocalInput, localInputToIso } from "./pure";

/**
 * 活动配置：Event 壳（标题 / 简介 / 起止时间）+ 模块节点 / 年级 / 寄达校 / 公告。
 *
 * 壳字段在活动开始后被服务端锁定（只接受模块字段），界面照常可编辑，保存时
 * 由服务端回 400 说明原因——前端不复制这套规则，避免两处真源。
 */
export default function ConfigTab() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);

  const [phaseLabel, setPhaseLabel] = useState("");
  const [eventStatus, setEventStatus] = useState("");
  const [counts, setCounts] = useState({ barcode: 0, registration: 0 });
  const [hasPdf, setHasPdf] = useState(false);

  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [startAt, setStartAt] = useState("");
  const [endAt, setEndAt] = useState("");
  const [shipAt, setShipAt] = useState("");
  const [distributeAt, setDistributeAt] = useState("");
  const [grades, setGrades] = useState<string[]>([]);
  const [schools, setSchools] = useState<AdminSchool[]>([]);
  const [body, setBody] = useState("");
  const [rteKey, setRteKey] = useState(0);
  const [pdf, setPdf] = useState<File | null>(null);
  const [clearPdf, setClearPdf] = useState(false);

  const [newRegion, setNewRegion] = useState(POSTCARD_REGIONS[0]);
  const [newSchool, setNewSchool] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const d = await postcardAdminApi.getConfig();
      setPhaseLabel(d.configured ? d.phase_label || "" : "尚未配置");
      setEventStatus(d.event?.status || "");
      setCounts({ barcode: d.barcode_count ?? 0, registration: d.registration_count ?? 0 });
      setHasPdf(Boolean(d.has_announcement_pdf));
      setTitle(d.event?.title || "");
      setSummary(d.event?.summary || "");
      setStartAt(isoToLocalInput(d.event?.start_at));
      setEndAt(isoToLocalInput(d.event?.end_at));
      setShipAt(isoToLocalInput(d.ship_at));
      setDistributeAt(isoToLocalInput(d.distribute_at));
      setGrades(d.allowed_grades?.length ? d.allowed_grades : POSTCARD_GRADES.map((g) => g.value));
      setSchools(d.destination_schools || []);
      setBody(d.announcement_body || "");
      setRteKey((k) => k + 1);
    } catch (e) {
      setError(isForbidden(e) ? "需要 manage_postcard 权限才能配置活动。" : errMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const grouped = useMemo(() => groupSchools(schools, POSTCARD_REGIONS), [schools]);

  const toggleGrade = (value: string) => {
    setGrades((prev) => (prev.includes(value) ? prev.filter((g) => g !== value) : [...prev, value]));
  };

  const addSchool = () => {
    const name = newSchool.trim();
    if (!name) return;
    if (schools.some((s) => s.region === newRegion && s.name === name)) {
      setNotice("该区已有同名学校。");
      return;
    }
    setSchools((prev) => [...prev, { region: newRegion, name }]);
    setNewSchool("");
    setNotice("");
  };

  const removeSchool = (region: string, name: string) => {
    setSchools((prev) => prev.filter((s) => !(s.region === region && s.name === name)));
  };

  const save = async () => {
    setNotice("");
    setError("");
    const startIso = localInputToIso(startAt);
    const endIso = localInputToIso(endAt);
    if (!title.trim()) return setError("请填写活动标题。");
    if (!startIso || !endIso) return setError("请填写登记开始与活动结束时间。");
    if (grades.length === 0) return setError("请至少选择一个可参与年级。");
    setSaving(true);
    try {
      await postcardAdminApi.saveConfig(
        {
          title: title.trim(),
          summary: summary.trim(),
          body,
          start_at: startIso,
          end_at: endIso,
          ship_at: localInputToIso(shipAt),
          distribute_at: localInputToIso(distributeAt),
          allowed_grades: grades,
          destination_schools: schools,
        },
        pdf,
        clearPdf,
      );
      setPdf(null);
      setClearPdf(false);
      setNotice("已保存。");
      await load();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const publish = async () => {
    setNotice("");
    setError("");
    setPublishing(true);
    try {
      await postcardAdminApi.publish();
      setNotice("活动已发布。");
      await load();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setPublishing(false);
    }
  };

  if (loading) return <p className="pa-muted">加载中…</p>;

  return (
    <div className="pa-stack">
      {error && <p className="pa-error">{error}</p>}
      {notice && <p className="pa-ok">{notice}</p>}

      <div className="pa-meta">
        <span>阶段：{phaseLabel || "—"}</span>
        <span>条码：{counts.barcode}</span>
        <span>登记单：{counts.registration}</span>
      </div>

      <section className="pa-card">
        <h3 className="pa-card-title">活动信息</h3>
        <label className="pa-field">
          <span>活动标题</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
        </label>
        <label className="pa-field">
          <span>简介（可选）</span>
          <input value={summary} onChange={(e) => setSummary(e.target.value)} maxLength={300} />
        </label>
        <div className="pa-grid2">
          <label className="pa-field">
            <span>登记开始</span>
            <input type="datetime-local" value={startAt} onChange={(e) => setStartAt(e.target.value)} />
          </label>
          <label className="pa-field">
            <span>活动结束</span>
            <input type="datetime-local" value={endAt} onChange={(e) => setEndAt(e.target.value)} />
          </label>
          <label className="pa-field">
            <span>寄出节点（可空 = 跳过）</span>
            <input type="datetime-local" value={shipAt} onChange={(e) => setShipAt(e.target.value)} />
          </label>
          <label className="pa-field">
            <span>下发节点（可空 = 跳过）</span>
            <input
              type="datetime-local"
              value={distributeAt}
              onChange={(e) => setDistributeAt(e.target.value)}
            />
          </label>
        </div>
        <p className="pa-hint">活动发布后，标题 / 简介 / 起止时间由服务端锁定；节点、学校清单与公告仍可修改。</p>
      </section>

      <section className="pa-card">
        <h3 className="pa-card-title">可参与年级</h3>
        <div className="pa-inline">
          {POSTCARD_GRADES.map((g) => (
            <label key={g.value} className="pa-check">
              <input
                type="checkbox"
                checked={grades.includes(g.value)}
                onChange={() => toggleGrade(g.value)}
              />
              {g.label}
            </label>
          ))}
        </div>
      </section>

      <section className="pa-card">
        <h3 className="pa-card-title">寄达校清单（{schools.length}）</h3>
        <div className="pa-inline">
          <select value={newRegion} onChange={(e) => setNewRegion(e.target.value)}>
            {POSTCARD_REGIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <input
            placeholder="学校名称"
            value={newSchool}
            maxLength={128}
            onChange={(e) => setNewSchool(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addSchool();
              }
            }}
          />
          <button type="button" className="btn btn-secondary btn-sm" onClick={addSchool}>
            添加
          </button>
        </div>
        {grouped.length === 0 ? (
          <p className="pa-muted">还没有寄达校。登记页的寄达校下拉由这份清单生成。</p>
        ) : (
          <div className="pa-schools">
            {grouped.map((g) => (
              <div key={g.region} className="pa-school-group">
                <strong>{g.region}</strong>
                <div className="pa-chips">
                  {g.names.map((name) => (
                    <span key={name} className="pa-chip">
                      {name}
                      <button
                        type="button"
                        aria-label={`删除 ${g.region} ${name}`}
                        onClick={() => removeSchool(g.region, name)}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="pa-card">
        <h3 className="pa-card-title">活动公告</h3>
        <RichTextEditor
          key={rteKey}
          content={body}
          onChange={setBody}
          minHeight={220}
          placeholder="活动公告正文（支持 Word 导入，仅保留文字与格式）"
          wordImport
        />
        <div className="pa-field pa-file">
          <span>公告 PDF 附件{hasPdf && !clearPdf ? "（已有）" : ""}</span>
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => {
              setPdf(e.target.files?.[0] ?? null);
              if (e.target.files?.[0]) setClearPdf(false);
            }}
          />
        </div>
        {hasPdf && (
          <label className="pa-check">
            <input type="checkbox" checked={clearPdf} onChange={(e) => setClearPdf(e.target.checked)} />
            删除已有 PDF 附件
          </label>
        )}
      </section>

      <div className="pa-actions">
        <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void save()}>
          {saving ? "保存中…" : "保存配置"}
        </button>
        {eventStatus === "draft" && (
          <button
            type="button"
            className="btn btn-secondary"
            disabled={publishing}
            onClick={() => void publish()}
          >
            {publishing ? "发布中…" : "发布活动"}
          </button>
        )}
      </div>
    </div>
  );
}
