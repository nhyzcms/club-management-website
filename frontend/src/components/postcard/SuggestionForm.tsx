import { useState } from "react";
import { postcardApi } from "../../api/postcard";
import { useTurnstile } from "../../turnstile";

interface Props {
  isMobile: boolean;
}

/**
 * 建议箱：内容（必填 ≤1000 字）+ 联系方式（选填 ≤128）。Turnstile + 双轨限流
 * 在服务端（SuggestionsView），前端只负责收集与反馈。
 */
export default function SuggestionForm({ isMobile }: Props) {
  const [content, setContent] = useState("");
  const [contact, setContact] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const { containerRef, token, reset, enabled } = useTurnstile(true);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    if (!content.trim()) {
      setError("建议内容不能为空");
      return;
    }
    if (enabled && !token) {
      setError("请先完成人机校验。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await postcardApi.suggest(content.trim(), contact.trim(), token);
      setContent("");
      setContact("");
      setDone(true);
      reset();
      window.setTimeout(() => setDone(false), 5000);
    } catch (err: any) {
      setError(err?.message || "提交失败，请稍后重试。");
      reset();
    } finally {
      setBusy(false);
    }
  };

  const primaryBtn = isMobile ? "m-btn-primary" : "btn btn-primary";

  return (
    <form className="pc-suggest" onSubmit={submit} noValidate>
      {error && (
        <div className="alert alert-danger" role="alert">
          <span>{error}</span>
        </div>
      )}
      {done && (
        <div className="alert alert-success" role="status">
          <span>感谢你的建议！</span>
        </div>
      )}
      <label className="label" htmlFor="pc-suggest-content">建议内容</label>
      <textarea
        id="pc-suggest-content"
        className="input pc-suggest-textarea"
        maxLength={1000}
        rows={3}
        placeholder="对本次明信片互寄活动的建议（流程 / 规则 / 体验均可）"
        value={content}
        onChange={(e) => setContent(e.target.value)}
      />
      <label className="label" htmlFor="pc-suggest-contact">联系方式（选填）</label>
      <input
        id="pc-suggest-contact"
        className="input"
        maxLength={128}
        placeholder="想被回复时填写（邮箱 / 社内账号等）"
        value={contact}
        onChange={(e) => setContact(e.target.value)}
      />
      {enabled && <div ref={containerRef} className="pc-turnstile" />}
      <button type="submit" className={primaryBtn} disabled={busy}>
        {busy ? "提交中…" : "提交建议"}
      </button>
    </form>
  );
}
