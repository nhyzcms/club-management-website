import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  postcardApi,
  purgePhotosBeacon,
  type PostcardPortal,
  type PostcardProgressNode,
  type PostcardRegistrationSummary,
  type RegisterResult,
} from "../api/postcard";
import AppShell from "../components/AppShell";
import MobilePage from "../components/MobilePage";
import RegisterForm from "../components/postcard/RegisterForm";
import HistorySection from "../components/postcard/HistorySection";
import LookupBox from "../components/postcard/LookupBox";
import SuggestionForm from "../components/postcard/SuggestionForm";
import { failedReviewTokens, needsReviewPoll, reviewOutcomeOf } from "../components/postcard/pure";
import { getPostcardFingerprint } from "../utils/fingerprint";
import { isMobileDevice } from "../utils/device";
import "../styles/postcard.css";

/**
 * 明信片互寄独立页（`/#/postcard`，主页按钮新标签页打开）。
 *
 * 5 阶段渲染（方案 §2）：
 * - 未开始 → 全屏「本年度活动未开始」（普通用户不见任何表单元数据）；
 * - 登记中 → 公告 + 进度 + 登记表单 + 历史 + 建议；
 * - 已寄出 / 下发中 → 公告 + 进度 + 阶段横幅 + 历史 + 建议（登记已截止）；
 * - 已结束 → 公告 + 进度 + 结束横幅 + 历史 + 建议（登记数据保留可查）。
 *
 * 一套内容两套外壳（桌面 AppShell / 手机 MobilePage），同「社员查询」模式。
 * 归属三轨：ncdid Cookie + 本地指纹 + 登录用户——历史记录自动归集。
 */
export default function PostcardPage() {
  const isMobile = isMobileDevice();
  const body = <PostcardContent isMobile={isMobile} />;

  if (isMobile) {
    return (
      <MobilePage title="明信片互寄" back="/m">
        {body}
      </MobilePage>
    );
  }
  return (
    <AppShell>
      <div className="page">
        <div className="container pc-container">{body}</div>
      </div>
    </AppShell>
  );
}

/** 阶段横幅文案（已寄出 / 下发中 / 已结束；登记中不需要横幅）。 */
const PHASE_BANNER: Record<string, string> = {
  shipped: "明信片已统一寄出，登记已截止。",
  distributing: "明信片下发中，请留意查收。",
  ended: "本次活动已结束，感谢参与！",
};

function fmtDateTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function ProgressStepper({ nodes }: { nodes: PostcardProgressNode[] }) {
  return (
    <ol className="pc-progress">
      {nodes.map((n) => (
        <li key={n.key} className={n.reached ? "reached" : ""}>
          <span className="pc-progress-dot" aria-hidden="true" />
          <span className="pc-progress-label">{n.label}</span>
          <span className="pc-progress-time">{fmtDateTime(n.time) || "时间待定"}</span>
        </li>
      ))}
    </ol>
  );
}

function PostcardContent({ isMobile }: { isMobile: boolean }) {
  const fingerprint = useMemo(getPostcardFingerprint, []);
  const [portal, setPortal] = useState<PostcardPortal | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [regs, setRegs] = useState<PostcardRegistrationSummary[] | null>(null);
  /** 提交后的审核状态机：审核中 → 发码（AI 通过 / 转人工）或 不发码（判不匹配）。 */
  const [submitState, setSubmitState] = useState<
    // 审核中 / 未通过时服务端不发登记码，前端用 access_token 轮询与申请复核。
    | { kind: "reviewing"; token: string; regCode: string | null }
    | { kind: "granted"; regCode: string; via: "ai" | "manual" }
    | { kind: "rejected"; token: string; regCode: string | null; mismatched: string[]; comment: string }
    | null
  >(null);
  const [reviewTimedOut, setReviewTimedOut] = useState(false);
  const [modalError, setModalError] = useState("");
  const [requestingReview, setRequestingReview] = useState(false);
  const [copied, setCopied] = useState(false);

  const regsRef = useRef<PostcardRegistrationSummary[] | null>(null);
  const pollCountRef = useRef(0);

  useEffect(() => {
    document.title = "明信片互寄 · 南汇一中传媒社";
  }, []);

  const loadPortal = useCallback(async () => {
    try {
      setPortal(await postcardApi.portal());
    } catch {
      setLoadError(true);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const d = await postcardApi.my(fingerprint);
      setRegs(d.results);
    } catch {
      /* 历史加载失败不阻塞页面（可手动刷新重试） */
    }
  }, [fingerprint]);

  useEffect(() => {
    void loadPortal();
  }, [loadPortal]);
  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);
  useEffect(() => {
    regsRef.current = regs;
  }, [regs]);

  // AI 审核结果轻量轮询：有待审条目时每 5s 刷一次历史，累计 12 次（约 1 分钟）
  // 后停止——之后靠手动刷新。AI 队列是后台线程，通常几秒内出结果。
  useEffect(() => {
    if (!regs || !needsReviewPoll(regs)) return;
    if (pollCountRef.current >= 12) return;
    const t = window.setInterval(() => {
      pollCountRef.current += 1;
      void loadHistory();
    }, 5000);
    return () => window.clearInterval(t);
  }, [regs, loadHistory]);

  // 关标签页：终态失败（AI/人工判不通过）的照片 sendBeacon 请求删除
  // （24h TTL 服务端兜底，方案 §7）。用 ref 读最新列表，监听器只挂一次。
  useEffect(() => {
    const onHide = () => {
      for (const token of failedReviewTokens(regsRef.current || [])) {
        purgePhotosBeacon(token);
      }
    };
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, [fingerprint]);

  const copyRegCode = async () => {
    if (!submitState || submitState.kind !== "granted") return;
    try {
      await navigator.clipboard.writeText(submitState.regCode);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* 剪贴板不可用（http 环境 / 旧浏览器）：用户可手动选中复制 */
    }
  };

  /** 登记提交成功（201）→ 按审核状态决定是否亮码（2026-11-08 用户指定规则）。 */
  const handleRegistered = (result: RegisterResult) => {
    pollCountRef.current = 0;
    setReviewTimedOut(false);
    setModalError("");
    void loadHistory();
    // 服务端权威：code_granted 为真才亮码（转人工 / 已通过）；否则只拿轮询凭证。
    if (result.code_granted && result.reg_code) {
      setSubmitState({
        kind: "granted",
        regCode: result.reg_code,
        via: result.review.state === "manual_pending" ? "manual" : "ai",
      });
    } else {
      setSubmitState({ kind: "reviewing", token: result.access_token, regCode: result.reg_code });
    }
  };

  /** 审核中轮询：2s 一次、最多 20 次（约 40s），出结论即停。 */
  useEffect(() => {
    if (!submitState || submitState.kind !== "reviewing") return;
    const token = submitState.token;
    let tries = 0;
    let stopped = false;
    const timer = window.setInterval(async () => {
      if (stopped) return;
      tries += 1;
      if (tries > 20) {
        setReviewTimedOut(true);
        stopped = true;
        window.clearInterval(timer);
        return;
      }
      try {
        const reg = await postcardApi.statusByToken(token);
        const outcome = reviewOutcomeOf(reg);
        if (outcome.kind === "granted") {
          stopped = true;
          window.clearInterval(timer);
          setSubmitState({ kind: "granted", regCode: reg.reg_code, via: outcome.via });
          void loadHistory();
        } else if (outcome.kind === "rejected") {
          stopped = true;
          window.clearInterval(timer);
          setSubmitState({
            kind: "rejected",
            token,
            regCode: reg.code_granted ? reg.reg_code : null,
            mismatched: outcome.mismatched,
            comment: outcome.comment,
          });
          void loadHistory();
        }
      } catch {
        /* 单次轮询失败不打断，下一轮再试 */
      }
    }, 2000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [submitState, loadHistory]);

  /** 判不匹配 → 申请人工复核：转 manual_pending 后立即发码（同「转人工」规则）。 */
  const requestManualReview = async () => {
    if (!submitState || submitState.kind !== "rejected" || requestingReview) return;
    const token = submitState.token;
    setRequestingReview(true);
    setModalError("");
    try {
      await postcardApi.requestReviewByToken(token);
      // 转人工后服务端立即发码：再拉一次状态拿真码。
      const reg = await postcardApi.statusByToken(token);
      setSubmitState({ kind: "granted", regCode: reg.reg_code, via: "manual" });
      pollCountRef.current = 0;
      void loadHistory();
    } catch (err: any) {
      setModalError(err?.message || "提交复核失败，请稍后重试。");
    } finally {
      setRequestingReview(false);
    }
  };

  if (loadError) {
    return (
      <div className="pc-gate">
        <h2>加载失败</h2>
        <p className="muted">网络异常，暂时拿不到活动状态。</p>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => {
            setLoadError(false);
            void loadPortal();
            void loadHistory();
          }}
        >
          重试
        </button>
      </div>
    );
  }

  if (!portal) {
    return <div className="pc-gate"><p className="muted">加载中…</p></div>;
  }

  // —— 未开始：普通用户全屏只见提示（需求钉死；管理员多一行提示）——
  if (portal.phase === "not_started") {
    return (
      <div className="pc-gate">
        <svg viewBox="0 0 24 24" className="pc-gate-icon" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M3 9l9-6 9 6v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" />
          <path d="m3 9 9 6 9-6" />
        </svg>
        <h2>本年度活动未开始</h2>
        <p className="muted">明信片互寄活动尚未开始，敬请期待。</p>
        {portal.is_admin && (
          <p className="pc-admin-hint">
            管理员可见：当前活动尚未开始或未配置。可以先去
            <a href="#/postcard/admin">管理端</a>
            填写起止时间、各节点与学校清单，或上传填写样例。
          </p>
        )}
      </div>
    );
  }

  const banner = PHASE_BANNER[portal.phase];
  const showForm = portal.can_register && portal.sample_ready;

  return (
    <>
      {portal.is_admin && (
        <div className="pc-admin-bar">
          <span>管理员可见</span>
          <a href="#/postcard/admin">管理端</a>
          <a href="#/postcard/receive" target="_blank" rel="noopener noreferrer">
            签收扫码
          </a>
        </div>
      )}

      {portal.event && (
        <section className="pc-card pc-announce">
          <h2>{portal.event.title}</h2>
          {portal.event.summary && <p className="muted">{portal.event.summary}</p>}
          {portal.announcement_body && (
            <div
              className="pc-announce-body"
              // 公告正文入库前已经 bleach 白名单净化（AdminConfigView PUT），
              // 这里原样渲染；表单字段全部纯文本转义，无第二处注入面。
              dangerouslySetInnerHTML={{ __html: portal.announcement_body }}
            />
          )}
          {portal.announcement_pdf && (
            <a
              className="pc-pdf-link"
              href={postcardApi.announcementPdfUrl()}
              target="_blank"
              rel="noopener"
            >
              查看公告 PDF
            </a>
          )}
        </section>
      )}

      {portal.progress.length > 0 && (
        <section className="pc-card">
          <h3 className="pc-card-title">活动进度</h3>
          <ProgressStepper nodes={portal.progress} />
        </section>
      )}

      {banner && <div className="pc-phase-banner">{banner}</div>}

      {portal.can_register && !portal.sample_ready && (
        <div className="pc-phase-banner pc-phase-banner-warn">
          活动填写样例尚未配置，暂不能登记；请联系管理员。
        </div>
      )}

      {showForm && (
        <section className="pc-card">
          <h3 className="pc-card-title">明信片登记</h3>
          <RegisterForm
            portal={portal}
            fingerprint={fingerprint}
            isMobile={isMobile}
            onRegistered={handleRegistered}
          />
        </section>
      )}

      <section className="pc-card">
        <h3 className="pc-card-title">查询登记情况</h3>
        <p className="muted pc-lookup-hint">
          换了设备或清过浏览器？用 6 位登记码或寄出人姓名找回登记。
        </p>
        <LookupBox
          portal={portal}
          fingerprint={fingerprint}
          isMobile={isMobile}
          onChanged={() => void loadHistory()}
        />
      </section>

      <section className="pc-card">
        <div className="pc-history-head">
          <h3 className="pc-card-title">历史登记记录</h3>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => {
              pollCountRef.current = 0;
              void loadHistory();
            }}
          >
            刷新
          </button>
        </div>
        {regs === null ? (
          <p className="muted">加载中…</p>
        ) : (
          <HistorySection
            regs={regs}
            portal={portal}
            fingerprint={fingerprint}
            isMobile={isMobile}
            onChanged={() => void loadHistory()}
          />
        )}
      </section>

      <section className="pc-card">
        <h3 className="pc-card-title">提建议</h3>
        <SuggestionForm isMobile={isMobile} />
      </section>

      {submitState && (
        <div className="pc-modal-mask" role="dialog" aria-modal="true" aria-label="登记审核">
          <div className="pc-modal">
            {submitState.kind === "reviewing" && (
              <>
                <h3>照片审核中…</h3>
                <div className="pc-modal-spinner" aria-hidden="true" />
                <p className="muted">
                  正在核对照片与填写信息是否一致，通常几秒内完成。
                </p>
                {reviewTimedOut && (
                  <p className="muted pc-modal-hint">
                    审核还在进行中。可以先关闭本窗口，结果稍后到「历史登记记录」查看。
                  </p>
                )}
                <button type="button" className="btn btn-ghost" onClick={() => setSubmitState(null)}>
                  关闭，稍后查看
                </button>
              </>
            )}

            {submitState.kind === "granted" && (
              <>
                <h3>登记成功</h3>
                <p className="muted">
                  {submitState.via === "ai"
                    ? "照片已通过 AI 审核，审核照片已自动删除。"
                    : "AI 审核暂不可用，已转人工复核；复核期间照片保留，通过后自动删除。"}
                </p>
                <div className="pc-modal-code tnum">{submitState.regCode}</div>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => void copyRegCode()}>
                  {copied ? "已复制 ✓" : "复制登记码"}
                </button>
                <p className="muted pc-modal-hint">
                  登记码是查看和修改登记记录的唯一凭证，请妥善保存。
                </p>
                <button type="button" className="btn btn-primary" onClick={() => setSubmitState(null)}>
                  我已保存登记码
                </button>
              </>
            )}

            {submitState.kind === "rejected" && (
              <>
                <h3>本次登记未通过审核</h3>
                <p className="pc-modal-mismatch">
                  照片与以下填写项不一致：
                  {submitState.mismatched.length > 0 ? submitState.mismatched.join("、") : "照片与填写信息"}
                  {submitState.comment ? `（${submitState.comment}）` : ""}
                </p>
                <p className="muted">
                  登记码暂不发放。如确认自己填写无误，可申请人工复核——转人工后立即发放登记码。
                </p>
                {modalError && <p className="pc-modal-error">{modalError}</p>}
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={requestingReview}
                  onClick={() => void requestManualReview()}
                >
                  {requestingReview ? "提交中…" : "申请人工复核"}
                </button>
                <button type="button" className="btn btn-ghost" onClick={() => setSubmitState(null)}>
                  关闭
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
