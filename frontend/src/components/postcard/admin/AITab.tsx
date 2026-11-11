import { useCallback, useEffect, useState } from "react";
import {
  postcardAdminApi,
  type AIConfig,
  type AIProbeInput,
  type AISample,
} from "../../../api/postcardAdmin";
import { errMessage, isForbidden } from "./pure";

/** 服务商预设：只填「接入差异」，模型 ID 仍可在下拉里按订阅自选。 */
type Preset = {
  key: string;
  label: string;
  baseUrl: string;
  model: string;
  headers: Record<string, string>;
  timeout: number;
};

/** OpenCode Go 用稳定会话串做路由 / prompt cache 键（缺失会 400 MissingSessionID）。 */
function opencodeSessionId(): string {
  return `nhyz-postcard-${Math.random().toString(36).slice(2, 10)}`;
}

/** 温度夹到 0–2（输入框清空 / 乱填时不要给后端发 NaN 或越界值）。 */
function clampTemp(raw: unknown): number {
  const n = Number(raw);
  if (!Number.isFinite(n)) return 0;
  return Math.min(2, Math.max(0, Math.round(n * 10) / 10));
}

/**
 * 预设来自各家官方文档（2026-11 核对）：
 * - DeepSeek：OpenAI 兼容 `https://api.deepseek.com/v1` + Bearer；`deepseek-flash`
 *   是现行模型（支持图片，明信片审图必需），`deepseek-chat` 已是旧别名。
 * - OpenCode-GO：`https://opencode.ai/zen/go/v1`，除 Bearer 外必须带
 *   `x-opencode-session`（稳定会话串）与自有 UA，否则 400 MissingSessionID。
 */
const PRESETS: Preset[] = [
  {
    key: "deepseek",
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
    model: "deepseek-flash",
    headers: {},
    timeout: 60,
  },
  {
    key: "opencode-go",
    label: "OpenCode-GO",
    baseUrl: "https://opencode.ai/zen/go/v1",
    model: "deepseek-v4.1-flash",
    headers: {
      "User-Agent": "nhyz-postcard-review/1.0",
      "x-opencode-client": "nhyz-postcard-review",
    },
    timeout: 60,
  },
];

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
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<
    { ok: boolean; text: string } | null
  >(null);

  const [config, setConfig] = useState<AIConfig | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [timeout, setTimeoutSec] = useState(20);
  const [temperature, setTemperature] = useState(0);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [headersText, setHeadersText] = useState("{}");
  const [blacklistText, setBlacklistText] = useState("");
  const [promptPrefix, setPromptPrefix] = useState("");
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelsBusy, setModelsBusy] = useState(false);
  const [modelsError, setModelsError] = useState("");

  const [samples, setSamples] = useState<AISample[]>([]);
  const [sampleFile, setSampleFile] = useState<File | null>(null);
  const [caption, setCaption] = useState("");
  const [explain, setExplain] = useState<
    { id: number; busy: boolean; text: string; error: string } | null
  >(null);

  /** 请求头 JSON → 对象；格式错时给出提示并返回 null（保存 / 拉列表共用）。 */
  const parseHeaders = useCallback((): Record<string, string> | null => {
    try {
      const parsed = JSON.parse(headersText || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("自定义请求头必须是 JSON 对象");
      }
      return Object.fromEntries(
        Object.entries(parsed as Record<string, unknown>).map(([k, v]) => [k, String(v)]),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "自定义请求头 JSON 格式有误");
      return null;
    }
  }, [headersText]);

  /**
   * 从服务商 `/models` 拉模型清单（可带未保存的草稿参数）。
   * 清单只来自服务商，前端不内置任何写死的模型名。
   */
  const fetchModels = useCallback(
    async (draft: {
      base_url: string;
      extra_headers: Record<string, string>;
      timeout_seconds: number;
      api_key?: string;
    }) => {
      const base = draft.base_url.trim();
      if (!base) {
        setModelOptions([]);
        setModelsError("请先填写 Base URL 再获取模型列表。");
        return;
      }
      setModelsBusy(true);
      setModelsError("");
      try {
        const d = await postcardAdminApi.aiModels({
          base_url: base,
          extra_headers: draft.extra_headers,
          timeout_seconds: draft.timeout_seconds,
          ...(draft.api_key ? { api_key: draft.api_key } : {}),
          dry_run: true,
        });
        if (d.ok) {
          setModelOptions(d.models ?? []);
          if (!d.models || d.models.length === 0) {
            setModelsError("服务商没有返回任何模型，请手动填写模型 ID。");
          }
        } else {
          setModelOptions([]);
          setModelsError(d.error || "获取模型列表失败。");
        }
      } catch (e) {
        setModelOptions([]);
        setModelsError(errMessage(e));
      } finally {
        setModelsBusy(false);
      }
    },
    [],
  );

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
      setTimeoutSec(cfg.timeout_seconds ?? 20);
      setTemperature(cfg.temperature ?? 0);
      // 还没配过 Base URL（首次上线 / 换服务商）时默认展开高级选项，省一次点击。
      if (!cfg.base_url) setAdvancedOpen(true);
      setHeadersText(JSON.stringify(cfg.extra_headers || {}, null, 2));
      setBlacklistText((cfg.ip_blacklist || []).join("\n"));
      setPromptPrefix(cfg.prompt_prefix || "");
      setSamples(sm.results);
      if (cfg.base_url) {
        // 打开页面就按已保存配置拉一次清单；失败只提示，不影响其他功能。
        void fetchModels({
          base_url: cfg.base_url,
          extra_headers: { ...(cfg.extra_headers || {}) },
          timeout_seconds: cfg.timeout_seconds ?? 20,
        });
      }
    } catch (e) {
      setError(isForbidden(e) ? "需要 manage_postcard 权限。" : errMessage(e));
    } finally {
      setLoading(false);
    }
  }, [fetchModels]);

  useEffect(() => {
    void load();
  }, [load]);

  /** 套用服务商预设：覆盖 Base URL / 模型 ID / 请求头 / 超时，不动 API Key 与开关。 */
  const applyPreset = (preset: Preset) => {
    if (
      (baseUrl.trim() || model.trim()) &&
      !window.confirm(`将覆盖当前 Base URL、模型 ID 与请求头，改为「${preset.label}」预设。继续？`)
    ) {
      return;
    }
    const headers: Record<string, string> = { ...preset.headers };
    if (preset.key === "opencode-go") {
      headers["x-opencode-session"] = opencodeSessionId();
    }
    setError("");
    setNotice(`已填入「${preset.label}」预设：填好 API Key 后点「测试连接」验证，通过再保存。`);
    setBaseUrl(preset.baseUrl);
    setModel(preset.model);
    setHeadersText(JSON.stringify(headers, null, 2));
    setTimeoutSec(preset.timeout);
    setModelOptions([]);
    setModelsError("");
    void fetchModels({
      base_url: preset.baseUrl,
      extra_headers: headers,
      timeout_seconds: preset.timeout,
      ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
    });
  };

  /** 「其他」= 自定义服务商：清空预设项，全部手填。 */
  const applyCustom = () => {
    const dirty = Boolean(baseUrl.trim() || model.trim() || headersText.trim() !== "{}");
    if (dirty && !window.confirm("将清空 Base URL、模型 ID 与请求头，改为自定义服务商。继续？")) return;
    setError("");
    setNotice("已切换为自定义服务商：请自行填写 Base URL、模型 ID 与请求头。");
    setBaseUrl("");
    setModel("");
    setHeadersText("{}");
    setTimeoutSec(20);
    setModelOptions([]);
    setModelsError("");
  };

  /** 用当前表单（含未保存改动）拉一次模型列表。 */
  const fetchModelsFromDraft = () => {
    const headers = parseHeaders();
    if (!headers) return;
    void fetchModels({
      base_url: baseUrl,
      extra_headers: headers,
      timeout_seconds: timeout,
      ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
    });
  };

  /**
   * 当前页面的草稿参数：测试连接 / 让 AI 读样例共用。
   *
   * 这两个按钮都要「填完先试、确认无误再保存」的用法，后端只在本次请求里用、
   * 不落库。早先读样例只认已保存配置，于是测试连接通过、读样例却报「配置不完整」。
   */
  const draftProbe = (headers: Record<string, string>): AIProbeInput => ({
    base_url: baseUrl.trim(),
    model: model.trim(),
    extra_headers: headers,
    timeout_seconds: timeout,
    temperature,
    prompt_prefix: promptPrefix,
    ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
  });

  const save = async () => {
    setError("");
    setNotice("");
    const headers = parseHeaders();
    if (!headers) return;
    setSaving(true);
    try {
      await postcardAdminApi.saveAIConfig({
        enabled,
        base_url: baseUrl.trim(),
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        model: model.trim(),
        timeout_seconds: timeout,
        temperature,
        extra_headers: headers,
        ip_blacklist: blacklistText
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
        prompt_prefix: promptPrefix,
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

  /** 测试连接：用当前页面填写的参数（含未保存改动）真发一次请求，后端不落库。 */
  const runTest = async () => {
    const headers = parseHeaders();
    if (!headers) return;
    setTesting(true);
    setTestResult(null);
    setError("");
    setNotice("");
    try {
      const d = await postcardAdminApi.testAIConfig(draftProbe(headers));
      if (d.ok) {
        setTestResult({
          ok: true,
          text: `连接正常 · ${d.latency_ms ?? "?"}ms · 模型 ${d.model || "—"} · 返回「${d.reply || ""}」`,
        });
      } else {
        setTestResult({ ok: false, text: d.error || "测试失败" });
      }
    } catch (e) {
      setTestResult({ ok: false, text: errMessage(e) });
    } finally {
      setTesting(false);
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

  const explainSample = async (id: number) => {
    // 带上当前草稿参数：否则「填好没保存」时测试连接能通、这个按钮必然报配置不完整。
    const headers = parseHeaders();
    if (!headers) return;
    setExplain({ id, busy: true, text: "", error: "" });
    try {
      const d = await postcardAdminApi.explainAISample(id, draftProbe(headers));
      setExplain({ id, busy: false, text: d.text, error: "" });
    } catch (e) {
      setExplain({ id, busy: false, text: "", error: errMessage(e) });
    }
  };

  if (loading) return <p className="pa-muted">加载中…</p>;

  return (
    <div className="pa-stack">
      {error && <p className="pa-error">{error}</p>}
      {notice && <p className="pa-ok">{notice}</p>}
      <p className="pa-hint">
        状态：{config?.ready ? "配置完整，AI 审核可用" : "配置不完整（Base URL / API Key / 模型 ID 缺一不可），登记会转人工复核"}
      </p>

      <section className="pa-card">
        <h3 className="pa-card-title">接口配置</h3>
        <div className="pa-inline">
          <span className="pa-hint">快捷预设：</span>
          {PRESETS.map((preset) => (
            <button
              key={preset.key}
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => applyPreset(preset)}
            >
              {preset.label}
            </button>
          ))}
          <button type="button" className="btn btn-secondary btn-sm" onClick={applyCustom}>
            其他
          </button>
        </div>
        <p className="pa-hint">
          预设只填 Base URL、模型 ID 与必需请求头；模型清单从该服务商的 /models 接口实时读取，可再自选。
        </p>
        <label className="pa-check">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          启用 AI 审核（关闭后登记全部转人工复核）
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
        <label className="pa-field">
          <span>模型选择（从服务商获取）</span>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={modelsBusy || modelOptions.length === 0}
          >
            <option value="">
              {modelsBusy
                ? "获取中…"
                : modelOptions.length
                  ? "请选择模型"
                  : "先点「获取模型列表」"}
            </option>
            {model && !modelOptions.includes(model) && (
              <option value={model}>{model}（当前）</option>
            )}
            {modelOptions.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <div className="pa-inline">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            disabled={modelsBusy}
            onClick={fetchModelsFromDraft}
          >
            {modelsBusy ? "获取中…" : "获取模型列表"}
          </button>
          {modelOptions.length > 0 && (
            <span className="pa-hint">已从服务商获取 {modelOptions.length} 个模型</span>
          )}
        </div>
        {modelsError && (
          <p className="pa-error" role="status">
            {modelsError}
          </p>
        )}
        <details
          className="pa-advanced"
          open={advancedOpen}
          onToggle={(e) => setAdvancedOpen((e.currentTarget as HTMLDetailsElement).open)}
        >
          <summary>高级选项（Base URL / 模型 ID / 超时 / 温度 / 自定义请求头）</summary>
          <p className="pa-hint">
            快捷预设会替你填好这几项；只有换服务商、要手动指定模型或调采样温度时才需要展开。
          </p>
          <label className="pa-field">
            <span>Base URL（OpenAI 兼容，含 /v1）</span>
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" />
          </label>
          <label className="pa-field">
            <span>模型 ID（可直接编辑）</span>
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="deepseek-flash" />
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
          <div className="pa-field">
            <span>温度（0–2，步进 0.1）：越低输出越确定、越可复现（审核建议 0）；越高越随机发散，1.5 以上容易跑题</span>
            <div className="pa-inline">
              <input
                type="range"
                min={0}
                max={2}
                step={0.1}
                value={temperature}
                aria-label="温度滑块"
                onChange={(e) => setTemperature(clampTemp(e.target.value))}
              />
              <input
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={temperature}
                aria-label="温度"
                className="pa-temp-num"
                onChange={(e) => setTemperature(clampTemp(e.target.value))}
              />
            </div>
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
        </details>
        <label className="pa-field">
          <span>网络动漫黑名单形象 IP（一行一个）</span>
          <textarea
            rows={6}
            value={blacklistText}
            onChange={(e) => setBlacklistText(e.target.value)}
            placeholder={"喜羊羊\n熊出没"}
          />
        </label>
        <label className="pa-field">
          <span>前置提示词（每次 AI 请求都会作为系统提示词附在最前）</span>
          <textarea
            rows={6}
            value={promptPrefix}
            onChange={(e) => setPromptPrefix(e.target.value)}
            placeholder={
              "例如：你是南汇一中传媒社的明信片审核员。判断以学校实际填写要求为准，" +
              "对学生使用简短、友善的中文说明。"
            }
          />
        </label>
        <p className="pa-hint">
          留空则不附加。审图、样例解读、海报识别与「测试连接」都会带上这段提示词；换新一年度时随其余配置自动继承。
        </p>
        <div className="pa-actions">
          <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void save()}>
            {saving ? "保存中…" : "保存 AI 配置"}
          </button>
          <button type="button" className="btn btn-secondary" disabled={testing} onClick={() => void runTest()}>
            {testing ? "测试中…" : "测试连接"}
          </button>
        </div>
        <p className="pa-hint">测试连接使用当前填写的参数（不落库）；保存后才会对正式审核生效。</p>
        {testResult && (
          <p className={testResult.ok ? "pa-ok" : "pa-error"} role="status">
            {testResult.ok ? "✅ " : "❌ "}
            {testResult.text}
          </p>
        )}
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
                <button
                  type="button"
                  className="pa-link pa-sample-ai-btn"
                  disabled={explain?.busy === true && explain.id === s.id}
                  onClick={() => void explainSample(s.id)}
                >
                  {explain?.id === s.id && explain.busy ? "AI 阅读中…" : "让 AI 读样例"}
                </button>
              </figure>
            ))}
          </div>
        )}

        {explain && (
          <div className="pa-ai-box" role="status">
            <div className="pa-ai-box-h">
              <span>AI 对样例 #{explain.id} 的理解</span>
              <button type="button" className="pa-link-danger" onClick={() => setExplain(null)}>
                关闭
              </button>
            </div>
            {explain.busy ? (
              <p className="pa-muted">AI 正在阅读这张样例…</p>
            ) : explain.error ? (
              <p className="pa-error">{explain.error}</p>
            ) : (
              <p className="pa-ai-text">{explain.text}</p>
            )}
            <p className="pa-hint">
              这是 AI 对样例要求的复述，用来核对它的理解是否与你的预期一致；它不影响审核判定本身。
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
