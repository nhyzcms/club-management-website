import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import AppShell from "../components/AppShell";
import { MEMBER_STATUS_LABELS } from "../types/member";
import "../styles/member.css";

interface CheckResult {
  found: boolean;
  name?: string;
  cohort?: number;
  code?: string;
  status?: string;
  avatar?: string | null;
}

/**
 * 公开扫码校验页（Part A / ADR-0025）：/#/v/:code?s=<签名>。
 *
 * 工牌二维码的扫描落地页，移动优先；只展示姓名 / 届数 / 组别 / 在册状态 / 头像（可选），
 * 电话、学号、邮箱等一律不展示。签名不符或码不存在时统一提示无效（不可区分）。
 */
export default function MemberVerifyPage() {
  const { code = "" } = useParams<{ code: string }>();
  const [search] = useSearchParams();
  const sig = search.get("s") || "";
  const [result, setResult] = useState<CheckResult | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    api.memberCheck(code, sig)
      .then((d: any) => {
        if (alive) setResult(d as CheckResult);
      })
      .catch((e: any) => {
        if (!alive) return;
        if (e?.status === 404) setResult({ found: false });
        else setErr(e.message || "校验失败，请稍后重试。");
      });
    return () => {
      alive = false;
    };
  }, [code, sig]);

  const statusLabel = result?.status ? MEMBER_STATUS_LABELS[result.status] ?? result.status : "";

  return (
    <AppShell>
      <div className="page">
        <div className="container" style={{ maxWidth: 420 }}>
          <div style={{ paddingTop: "var(--s-12)", paddingBottom: "var(--s-12)" }}>
            <div className="card card-pad center">
              <h2 style={{ marginBottom: "var(--s-4)" }}>社员身份校验</h2>
              {err ? (
                <p className="muted">{err}</p>
              ) : !result ? (
                <p className="muted">校验中…</p>
              ) : result.found ? (
                <>
                  {result.avatar && <img className="member-verify-avatar" src={result.avatar} alt="" />}
                  <div className="member-verify-name">{result.name}</div>
                  <p className="muted">
                    第 {result.cohort} 届
                  </p>
                  <p>
                    <span
                      className={
                        "badge " + (result.status === "active" ? "badge-success" : "badge-ghost")
                      }
                    >
                      {statusLabel}
                    </span>
                  </p>
                  <p className="muted member-verify-code">识别码 {result.code}</p>
                  <p className="muted">本页来自工牌二维码，仅展示公开信息。</p>
                </>
              ) : (
                <p className="muted">未找到匹配的社员身份——二维码无效、已失效或不属于本站。</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
