import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { activityApi } from "../api/activities";
import type { ActivityDetail } from "../types/activities";
import { ACTIVITY_TYPE_META, activityPhase } from "../types/activities";
import SurveyFill from "../components/SurveyFill";
import MobileTabBar from "../components/MobileTabBar";
import { useLoginModal } from "../components/LoginModalProvider";
import "../styles/mobile.css";

const fmtDate = (d: string | null): string => {
  if (!d) return "";
  const dt = new Date(d);
  return `${dt.getFullYear()}年${dt.getMonth() + 1}月${dt.getDate()}日`;
};

/** 手机版活动详情（/m/activity/:id）：信息 + 众议投票 + 调研作答 + 展示画廊。 */
export default function MobileActivityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { openLogin, authNonce } = useLoginModal();
  const [a, setA] = useState<ActivityDetail | null>(null);
  const [user, setUser] = useState<{ id: number } | null | undefined>(undefined);
  const [loadError, setLoadError] = useState("");
  const [loadStatus, setLoadStatus] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<number[]>([]);

  useEffect(() => {
    api.me()
      .then((d) => setUser({ id: d.user.id }))
      .catch(() => setUser(null));
  }, [authNonce]);

  useEffect(() => {
    if (!id) return;
    setLoadError("");
    setLoadStatus(0);
    setA(null);
    activityApi
      .get(Number(id))
      .then((d) => {
        setA(d);
        setSelected(d.my_selections ?? []);
        document.title = `${d.title} · 南汇一中传媒社`;
      })
      .catch((err: { message?: string; status?: number }) => {
        setLoadError(err.message || "加载失败");
        setLoadStatus(err.status || 0);
      });
  }, [id, authNonce]);

  const goBack = () => {
    const st = window.history.state as { idx?: number } | null;
    if (st && typeof st.idx === "number" && st.idx > 0) navigate(-1);
    else navigate("/m/activity");
  };

  const doVote = async () => {
    if (!a || selected.length < 1) return;
    setBusy(true);
    setError("");
    try {
      const d = await activityApi.vote(a.id, selected);
      setA(d);
      setSelected(d.my_selections ?? []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggleOption = (oid: number) => {
    if (!a) return;
    setSelected((cur) => {
      if (cur.includes(oid)) return cur.filter((x) => x !== oid);
      if (a.max_choices_per_voter === 1) return [oid];
      if (cur.length >= a.max_choices_per_voter) return cur;
      return [...cur, oid];
    });
  };

  let body: ReactNode = null;
  if (!a) {
    if (user === undefined || !loadError) {
      body = <p className="m-empty">加载中…</p>;
    } else {
      const needLogin = !user && (loadStatus === 404 || loadStatus === 403);
      body = needLogin ? (
        <div className="m-detail">
          <div className="m-detail-sec">
            <h3>需要登录</h3>
            <p className="m-hint" style={{ marginBottom: 12 }}>
              该互动仅登录成员可见。众议、征集、展示及仅成员调研需登录后查看。
            </p>
            <button className="m-btn-primary" onClick={() => openLogin(location.pathname + location.search)}>登录</button>
          </div>
        </div>
      ) : (
        <p className="m-empty">{loadError}</p>
      );
    }
  } else {
    const meta = ACTIVITY_TYPE_META[a.type];
    const phase = activityPhase(a.type, a.status);
    const isDeliberation = a.type === "deliberation";
    const isSurvey = a.type === "survey";
    const isCollection = a.type === "collection";
    const isExhibition = a.type === "exhibition";
    const options = a.options ?? [];
    const total = a.total_ballots ?? 0;
    const canVote = isDeliberation && a.status === "open" && a.my_selections === null;
    const surveyApproved = !a.review_status || a.review_status === "approved";
    const canFillSurvey =
      isSurvey && a.status === "open" && surveyApproved && a.my_response == null &&
      (a.audience === "public" || !!user);

    body = (
      <article className="m-detail">
        <div className="m-detail-medals">
          <span className="act-medal act-medal--sm"><span className="act-medal-ico">{meta?.emoji}</span>{meta?.label || a.type}</span>
          <span className={"act-medal act-medal--sm " + phase.medalClass}>{phase.emoji} {phase.label}</span>
          {a.audience === "public" && <span className="act-medal act-medal--sm medal-phase-neutral">公开</span>}
        </div>
        <h1 className="m-detail-title">{a.title}</h1>
        <div className="m-detail-meta">
          <span>{a.creator?.nickname || a.creator?.username || "—"}</span>
          {a.start_at && (<><span className="dot">·</span><span>{fmtDate(a.start_at)} 起</span></>)}
          {a.is_permanent ? (
            <><span className="dot">·</span><span>长期有效</span></>
          ) : a.end_at && (
            <><span className="dot">·</span><span>至 {fmtDate(a.end_at)}</span></>
          )}
        </div>

        {a.body ? (
          <div className="m-detail-body" dangerouslySetInnerHTML={{ __html: a.body }} />
        ) : null}

        {error && <div className="alert alert-danger" style={{ marginTop: 14 }}><span>{error}</span></div>}

        {isDeliberation && (
          <section className="m-detail-sec">
            <h3>投票</h3>
            {canVote ? (
              <>
                <p className="m-hint">可选 {a.max_choices_per_voter} 项（{a.max_choices_per_voter === 1 ? "一人一票" : "一人多票"}）；一经投出不可更改。</p>
                {options.map((o) => {
                  const on = selected.includes(o.id);
                  return (
                    <label key={o.id} className={"m-vote-opt" + (on ? " is-on" : "")}>
                      <input
                        type={a.max_choices_per_voter === 1 ? "radio" : "checkbox"}
                        name="vote"
                        checked={on}
                        onChange={() => toggleOption(o.id)}
                      />
                      <span>{o.text}</span>
                    </label>
                  );
                })}
                <button className="m-btn-primary" onClick={doVote} disabled={busy || selected.length < 1}>
                  {busy ? "提交中…" : "投票"}
                </button>
              </>
            ) : (
              <>
                {a.my_selections !== null && (
                  <p className="m-hint">你投了：{a.my_selections.map((oid) => options.find((o) => o.id === oid)?.text).filter(Boolean).join("、")}</p>
                )}
                {options.map((o) => {
                  const pct = total > 0 ? Math.round((o.vote_count / total) * 100) : 0;
                  return (
                    <div key={o.id} className="m-vote-result">
                      <div className="row"><span>{o.text}</span><span className="muted">{o.vote_count} 票 · {pct}%</span></div>
                      <div className="m-vote-bar"><i style={{ width: `${pct}%` }} /></div>
                    </div>
                  );
                })}
                <p className="m-hint" style={{ marginTop: 10, marginBottom: 0 }}>
                  共 {total} 人投票{a.is_secret_ballot ? "（秘密投票，明细不公开）" : ""}
                </p>
              </>
            )}
          </section>
        )}

        {isSurvey && (
          <section className="m-detail-sec">
            <h3>问卷</h3>
            {a.status === "scheduled" && <p className="m-hint">调研尚未开始，开始后即可作答。</p>}
            {a.status === "open" && !surveyApproved && <p className="m-hint">审核通过后即可作答。</p>}
            {a.status === "open" && surveyApproved && a.my_response != null && <p className="m-hint">你已经提交过了。</p>}
            {a.status === "closed" && (
              <p className="m-hint">征答已结束。{a.response_count != null ? `已收到 ${a.response_count} 份作答。` : ""}</p>
            )}
            {canFillSurvey && (
              <SurveyFill
                schema={a.schema || { pages: [{ name: "page1", elements: [] }] }}
                onComplete={async (answers) => {
                  setBusy(true);
                  setError("");
                  try {
                    const d = await activityApi.respond(a.id, answers);
                    setA(d);
                  } catch (e: unknown) {
                    setError(e instanceof Error ? e.message : String(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              />
            )}
          </section>
        )}

        {isCollection && (
          <section className="m-detail-sec">
            <h3>投稿</h3>
            {a.my_submission ? (
              <p className="m-hint" style={{ marginBottom: 0 }}>你已提交（{a.my_submission.files.length} 个文件）。</p>
            ) : a.status === "open" || a.status === "collecting" ? (
              <p className="m-hint" style={{ marginBottom: 0 }}>本互动为作品征集；投稿请在电脑端打开完整页面进行。</p>
            ) : (
              <p className="m-hint" style={{ marginBottom: 0 }}>征件未开放。</p>
            )}
          </section>
        )}

        {isExhibition && (a.exhibits?.length ?? 0) > 0 && (
          <section className="m-detail-sec">
            <h3>展品</h3>
            <div className="m-gallery">
              {a.exhibits!.map((ex) => {
                const img = ex.files.find((f) => f.file_type === "image");
                return img ? (
                  <img key={ex.id} src={img.file_url} alt={ex.title} loading="lazy" />
                ) : (
                  <div key={ex.id} className="m-gallery-ph">{ex.title}</div>
                );
              })}
            </div>
          </section>
        )}
      </article>
    );
  }

  return (
    <div className="m-app">
      <header className="m-topbar">
        <button className="m-back" onClick={goBack} aria-label="返回">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6" /></svg>
          返回
        </button>
      </header>
      {body}
      <MobileTabBar />
    </div>
  );
}
