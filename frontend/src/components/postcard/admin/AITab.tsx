import { useCallback, useEffect, useState } from "react";
import {
  postcardAdminApi,
  type AIConfig,
  type AISample,
} from "../../../api/postcardAdmin";
import { errMessage, isForbidden } from "./pure";

/**
 * AI 审核配置（全局单例）+ 填写样例。
 *
 * api_key 写后不可读：只显示「已设置」，留空保存 = 保持原值。
 * 样例是登记开放的前置条件（sample_ready），活动开始前必须至少一张。
 */
export default function AITab() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);

  const [config, setConfig] = useState<AIConfig | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [timeout, setTimeoutSec] = useState(30);
  const [headersText, setHeadersText] = useState("{}");
  const [blacklistText, setBlacklistText] = useState("");

  const [samples, setSamples] = useState<AISample[]>([]);
  const [sampleFile, setSampleFile] = useState<File | null>(null);
  const [caption, setCaption] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [cfg, sm] = await Promise.all([
        postcardAdminApi.aiConfig(),
        postcardAdminApi.aiSamples(),
      ]);
      setConfig(cfg);
      setEnabled(Boolean(cfg.enabled));
      setBaseUrl(cfg.base_url || "");
      setModel(cfg.model || "");
      setTimeoutSec(cfg.timeout_seconds ?? 30);
      setHeadersText(JSON.stringify(cfg.extra_headers || {}, null, 2));
      setBlacklistText((cfg.ip_blacklist || []).join("\n"));
      setSamples(sm.results);
    } catch (e) {
      setError(isForbidden(e) ? "需要 manage_postcard 权限。" : errMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    setError("");
    setNotice("");
    let headers: Record<string, string>;
    try {
      const parsed = JSON.parse(headersText || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("自定义请求头必须是 JSON 对象");
      }
      headers = Object.fromEntries(
        Object.entries(parsed as Record<string, unknown>).map(([k, v]) => [k, String(v)]),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "自定义请求头 JSON 格式有误");
      return;
    }
    setSaving(true);
    try {
      await postcardAdminApi.saveAIConfig({
        enabled,
        base_url: baseUrl.trim(),
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        model: model.trim(),
        timeout_seconds: timeout,
        extra_headers: headers,
        ip_blacklist: blacklistText
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setApiKey("");
      setNotice("AI 配置已保存。");
      await load();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const uploadSample = async () => {
    if (!sampleFile) return setError("请选择一张样例照片。");
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await postcardAdminApi.uploadAISample(sampleFile, caption.trim());
      setSampleFile(null);
      setCaption("");
      setNotice("样例已上传。");
      await load();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const removeSample = async (id: number) => {
    if (!window.confirm("确定删除这张样例照片？")) return;
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await postcardAdminApi.deleteAISample(id);
      setNotice("样例已删除。");
      await load();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <p className="pa-muted">加载中…</p>;

  return (
    <div className="pa-stack">
      {error && <p className="pa-error">{error}</p>}
      {notice && <p className="pa-ok">{notice}</p>}
      <p className="pa-hint">
        状态：{config?.ready ? "配置完整，AI 审核可用" : "配置不完整（base_url / api_key / model 缺一不可），登记会转人工复核"}
      </p>

      <section className="pa-card">
        <h3 className="pa-card-title">接口配置</h3>
        <label className="pa-check">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          启用 AI 审核（关闭后登记全部转人工复核）
        </label>
        <label className="pa-field">
          <span>Base URL（OpenAI 兼容，含 /v1）</span>
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" />
        </label>
        <label className="pa-field">
          <span>API Key{config?.api_key_set ? "（已设置，留空保持不变）" : ""}</span>
          <input
            type="password"
            value={apiKey}
            autoComplete="new-password"
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={config?.api_key_set ? "••••••••" : "sk-…"}
          />
        </label>
        <div className="pa-grid2">
          <label className="pa-field">
            <span>模型</span>
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="gpt-4o-mini" />
          </label>
          <label className="pa-field">
            <span>超时（秒，5–120）</span>
            <input
              type="number"
              min={5}
              max={120}
              value={timeout}
              onChange={(e) => setTimeoutSec(Number(e.target.value))}
            />
          </label>
        </div>
        <label className="pa-field">
          <span>自定义请求头（JSON 对象）</span>
          <textarea
            rows={3}
            value={headersText}
            onChange={(e) => setHeadersText(e.target.value)}
            spellCheck={false}
          />
        </label>
        <label className="pa-field">
          <span>网络动漫黑名单形象 IP（一行一个）</span>
          <textarea
            rows={6}
            value={blacklistText}
            onChange={(e) => setBlacklistText(e.target.value)}
            placeholder={"喜羊羊\n熊出没"}
          />
        </label>
        <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void save()}>
          {saving ? "保存中…" : "保存 AI 配置"}
        </button>
      </section>

      <section className="pa-card">
        <h3 className="pa-card-title">填写样例（{samples.length}）</h3>
        <p className="pa-hint">
          活动开始前必须上传填写样例，否则登记接口不开放。样例会作为 AI 比对基准，也会在登记页展示。
        </p>
        <div className="pa-inline">
          <input
            type="file"
            accept="image/*"
            onChange={(e) => setSampleFile(e.target.files?.[0] ?? null)}
          />
          <input
            placeholder="说明（可选）"
            value={caption}
            maxLength={500}
            onChange={(e) => setCaption(e.target.value)}
          />
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void uploadSample()}>
            上传
          </button>
        </div>
        {samples.length > 0 && (
          <div className="pa-samples">
            {samples.map((s) => (
              <figure key={s.id} className="pa-sample">
                <img src={postcardAdminApi.aiSampleImageUrl(s.id)} alt={s.caption || "填写样例"} loading="lazy" />
                <figcaption>
                  <span>{s.caption || "（无说明）"}</span>
                  <button type="button" className="pa-link-danger" onClick={() => void removeSample(s.id)}>
                    删除
                  </button>
                </figcaption>
              </figure>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
