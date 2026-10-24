import { useEffect, useState } from "react";
import {
  redirectToStepUp,
  stepupApi,
  type StepupBankItem,
  type StepupEvent,
  type StepupQuestion,
  type StepupStatus,
} from "../../api/stepup";
import "../../styles/stepup.css";

/**
 * 「安全验证」面板（ADR-0026）：方式状态 / 安全问题管理 / 最近验证记录。
 * - 首次设置问答＝重输登录密码；更换 / 清除＝grant（缺 → 跳验证页，完成后回来重试）。
 */
export default function SecurityPanel() {
  const [status, setStatus] = useState<StepupStatus | null>(null);
  const [mine, setMine] = useState<StepupQuestion[]>([]);
  const [bank, setBank] = useState<StepupBankItem[]>([]);
  const [events, setEvents] = useState<StepupEvent[]>([]);
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState("");

  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    stepupApi.status().then(setStatus).catch((e: any) => setErr(e.message || "加载失败"));
    stepupApi.questions().then((d) => { setMine(d.mine); setBank(d.bank); }).catch(() => {});
    stepupApi.events().then((d) => setEvents(d.results)).catch(() => {});
  };
  useEffect(load, []);

  const firstTime = mine.length === 0;

  const startEdit = () => {
    setEditing(true);
    setNotice("");
    setErr("");
    setSelected([]);
    setAnswers({});
  };

  const toggleQuestion = (key: string) => {
    setSelected((prev) => {
      if (prev.includes(key)) return prev.filter((k) => k !== key);
      if (prev.length >= 3) return prev;
      return [...prev, key];
    });
  };

  const save = () => {
    const items = selected.map((key) => ({ key, answer: (answers[key] || "").trim() }));
    if (items.length === 0 || items.some((i) => !i.answer)) {
      setErr("请选择 1–3 题，并为每题填写答案。");
      return;
    }
    setBusy(true);
    setErr("");
    stepupApi
      .questionsSet(items, firstTime ? password : undefined)
      .then(() => {
        setNotice("安全问题已更新。");
        setEditing(false);
        setPassword("");
        load();
      })
      .catch((e: any) => {
        if (e?.status === 403) {
          redirectToStepUp("manage_questions", "/security?tab=questions");
          return;
        }
        setErr(e.message || "保存失败");
      })
      .finally(() => setBusy(false));
  };

  const clear = () => {
    setBusy(true);
    setErr("");
    stepupApi
      .questionsSet([])
      .then(() => {
        setNotice("安全问题已清除。");
        load();
      })
      .catch((e: any) => {
        if (e?.status === 403) {
          redirectToStepUp("manage_questions", "/security?tab=questions");
          return;
        }
        setErr(e.message || "清除失败");
      })
      .finally(() => setBusy(false));
  };

  const methodLabel = (m: string) => (m === "email" ? "邮箱验证码" : m === "question" ? "安全问题" : m);

  return (
    <div className="card card-pad">
      <h2 className="profile-panel-title">安全验证</h2>
      <p className="muted">
        敏感操作（修改密码、换绑邮箱、管理安全问题）前需要确认「是本人」。验证通过后 10 分钟内同一操作免复验。
      </p>

      {err && <div className="alert alert-danger" role="alert" style={{ marginBottom: "var(--s-3)" }}><span>{err}</span></div>}
      {notice && <div className="alert alert-success" role="status" style={{ marginBottom: "var(--s-3)" }}><span>{notice}</span></div>}

      {!status ? (
        <p className="muted">加载中…</p>
      ) : (
        <>
          <ul className="muted" style={{ margin: "0 0 var(--s-4)", paddingLeft: "1.2em" }}>
            <li>
              邮箱验证码：{status.email.available ? <>可用（{status.email.address}）</> : "不可用——先在「账号认证」完成邮箱认证"}
            </li>
            <li>安全问题：{status.questions.configured ? `已设置 ${status.questions.count} 题` : "未设置"}</li>
          </ul>

          <h3 style={{ fontSize: 15, marginBottom: "var(--s-2)" }}>安全问题</h3>
          {!editing ? (
            <>
              {mine.length > 0 && (
                <ol className="muted" style={{ margin: "0 0 var(--s-3)", paddingLeft: "1.2em" }}>
                  {mine.map((q) => (
                    <li key={q.id}>{q.text}</li>
                  ))}
                </ol>
              )}
              <div style={{ display: "flex", gap: "var(--s-2)", flexWrap: "wrap" }}>
                <button className="btn btn-sm" type="button" onClick={startEdit}>
                  {firstTime ? "设置安全问题" : "更换安全问题"}
                </button>
                {!firstTime && (
                  <button className="btn btn-sm" type="button" disabled={busy} onClick={clear}>
                    清除
                  </button>
                )}
              </div>
              {firstTime && (
                <p className="muted" style={{ marginTop: "var(--s-2)" }}>
                  首次设置需输入<strong>登录密码</strong>确认身份（防止「只偷到会话」的人借此改密码）。
                </p>
              )}
            </>
          ) : (
            <>
              <div className="stepup-qbank">
                {bank.map((item) => (
                  <label key={item.key} className={"stepup-qbank-item" + (selected.includes(item.key) ? " is-picked" : "")}>
                    <input
                      type="checkbox"
                      checked={selected.includes(item.key)}
                      onChange={() => toggleQuestion(item.key)}
                    />
                    <span style={{ flex: 1 }}>{item.text}</span>
                    {selected.includes(item.key) && (
                      <input
                        className="input"
                        style={{ maxWidth: 220 }}
                        placeholder="你的答案"
                        aria-label={item.text}
                        value={answers[item.key] || ""}
                        onChange={(e) => setAnswers((prev) => ({ ...prev, [item.key]: e.target.value }))}
                      />
                    )}
                  </label>
                ))}
              </div>
              {firstTime && (
                <div className="field">
                  <label className="label" htmlFor="stepup-setup-pw">登录密码（首次设置需确认）</label>
                  <input
                    className="input"
                    id="stepup-setup-pw"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>
              )}
              <div style={{ display: "flex", gap: "var(--s-2)", marginTop: "var(--s-3)" }}>
                <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={save}>
                  {busy ? "保存中…" : "保存"}
                </button>
                <button className="btn btn-sm" type="button" onClick={() => setEditing(false)}>
                  取消
                </button>
              </div>
              <p className="muted" style={{ marginTop: "var(--s-2)" }}>答案不区分大小写与全半角，保存后不再显示（只存哈希）。</p>
            </>
          )}

          <h3 style={{ fontSize: 15, margin: "var(--s-5) 0 var(--s-2)" }}>最近验证记录</h3>
          {events.length === 0 ? (
            <p className="muted">暂无记录。</p>
          ) : (
            <div className="stepup-events">
              {events.map((ev, i) => (
                <div key={i} className="muted">
                  {new Date(ev.created_at).toLocaleString("zh-CN")} · {ev.scope_label} · {methodLabel(ev.method)} ·{" "}
                  {ev.result === "ok" ? "通过" : "失败"}
                  {ev.ip ? ` · ${ev.ip}` : ""}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
