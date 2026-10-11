import { useEffect, useState } from "react";
import { activityApi } from "../../api/activities";
import type { ActivityDetail, ActivityListItem } from "../../types/activities";
import type { Attachment } from "../../types/tasks";
import Avatar from "../../components/Avatar";
import type { ActivityPanelProps } from "./types";

function renderExFile(f: Attachment) {
  if (f.file_type === "image") return <img key={f.id} src={f.file_url} alt={f.file_name} width={800} height={600} loading="lazy" />;
  if (f.file_type === "video") return <video key={f.id} src={f.file_url} controls />;
  return <a key={f.id} href={f.file_url} target="_blank" rel="noreferrer" className="muted">{f.file_name}</a>;
}

export default function ExhibitionPanel({
  a, setActivity, user, busy, setBusy, setError,
}: ActivityPanelProps) {
  const [newTitle, setNewTitle] = useState("");
  const [newFiles, setNewFiles] = useState<File[]>([]);
  const [importOpen, setImportOpen] = useState(false);
  const [collections, setCollections] = useState<ActivityListItem[]>([]);
  const [pickedCollection, setPickedCollection] = useState<number | null>(null);
  const [pickedSubs, setPickedSubs] = useState<number[]>([]);
  const [collectionDetail, setCollectionDetail] = useState<ActivityDetail | null>(null);
  const [selected, setSelected] = useState<number[]>(a.my_selections ?? []);

  const isOwner = !!user && a.creator?.id === user.id;
  const canManage = !!user && (isOwner || !!user.can_change_activity);
  const canManageExhibits = canManage && (a.status === "scheduled" || a.status === "open");
  const canEditExhibit = canManage && a.status === "scheduled";
  const votingActive = a.voting_enabled;
  const voted = a.my_selections !== null;
  const mySel = a.my_selections ?? [];
  const canVote = votingActive && a.status === "open" && !voted;
  const total = a.total_ballots ?? 0;

  useEffect(() => {
    setSelected(a.my_selections ?? []);
  }, [a.my_selections]);

  const toggleOption = (oid: number) => {
    setSelected((cur) => {
      if (cur.includes(oid)) return cur.filter((x) => x !== oid);
      if (a.max_choices_per_voter === 1) return [oid];
      if (cur.length >= a.max_choices_per_voter) return cur;
      return [...cur, oid];
    });
  };

  const run = async (fn: () => Promise<ActivityDetail>): Promise<boolean> => {
    setBusy(true); setError("");
    try { setActivity(await fn()); return true; }
    catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); return false; }
    finally { setBusy(false); }
  };

  const doVote = () => { if (selected.length >= 1) void run(() => activityApi.vote(a.id, selected)); };
  const doRate = (eid: number, choice: "like" | "dislike") => void run(() => activityApi.rate(a.id, eid, choice));
  const doAddExhibit = async () => {
    if (newFiles.length < 1) return;
    if (await run(() => activityApi.addExhibit(a.id, newTitle.trim(), newFiles))) {
      setNewTitle(""); setNewFiles([]);
    }
  };
  const doUpdateExhibit = async (eid: number, curTitle: string) => {
    const t = window.prompt("修改展品标题（留空则不变）：", curTitle);
    if (t === null) return;
    void run(() => activityApi.updateExhibit(a.id, eid, t, null));
  };
  const doDeleteExhibit = async (eid: number) => {
    if (!window.confirm("删除该展品？")) return;
    void run(() => activityApi.deleteExhibit(a.id, eid));
  };
  const openImport = async () => {
    setImportOpen(true);
    const list = await activityApi.list({ type: "collection" });
    setCollections(list.results);
    if (list.results.length > 0) {
      setPickedCollection(list.results[0].id);
      setCollectionDetail(await activityApi.get(list.results[0].id));
    }
  };
  const pickCollection = async (cid: number) => {
    setPickedCollection(cid);
    setPickedSubs([]);
    setCollectionDetail(await activityApi.get(cid));
  };
  const doImport = async () => {
    if (pickedSubs.length < 1 || pickedCollection == null) return;
    if (await run(() => activityApi.importFromCollection(a.id, pickedCollection, pickedSubs))) {
      setImportOpen(false); setPickedSubs([]);
    }
  };

  const curateBar = (
    <>
      <span>{a.status === "scheduled" ? "布展中（待开始）——可加 / 改 / 删展品，或从征集导入；开放后仍可加 / 删，但标题锁定。" : "展示中——可继续加 / 导入 / 删展品；已上架展品的标题已锁定。"}</span>
      <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <input className="input" style={{ flex: "1 1 160px" }} value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="新展品标题（选填）" />
        <input type="file" multiple onChange={(e) => setNewFiles(Array.from(e.target.files || []))} />
        <button className="btn btn-primary btn-sm" onClick={() => void doAddExhibit()} disabled={busy || newFiles.length < 1}>+ 加展品</button>
        <button className="btn btn-ghost btn-sm" onClick={() => void openImport()}>从征集导入</button>
      </div>
    </>
  );

  return (
    <div className="card card-pad" style={{ marginTop: "var(--s-4)" }}>
      <h3 className="section-h">展品 ({a.exhibits?.length || 0})</h3>
      {canVote && (
        <div className="hint" style={{ marginBottom: 8 }}>
          投票：可选 {a.max_choices_per_voter} 个展品（{a.max_choices_per_voter === 1 ? "一人一展品" : "一人多展品"}），一经投出不可更改。赞/踩另算、可随时改。
        </div>
      )}
      {canManageExhibits && (
        canVote ? (
          <details style={{ marginBottom: 12 }}>
            <summary className="muted" style={{ cursor: "pointer" }}>布展 / 管理</summary>
            <div className="alert alert-info" style={{ marginTop: 8 }}>{curateBar}</div>
          </details>
        ) : (
          <div className="alert alert-info" style={{ marginBottom: 12 }}>{curateBar}</div>
        )
      )}
      {importOpen && (
        <div className="card card-pad" style={{ margin: "12px 0", background: "var(--c-surface-2, #f9fafb)" }}>
          <h4 className="section-h">从征集导入</h4>
          {collections.length === 0 ? (
            <>
              <p className="muted">暂无可导入的征集（先发起一场征集收件）。</p>
              <button className="btn btn-ghost btn-sm" onClick={() => setImportOpen(false)}>关闭</button>
            </>
          ) : (
            <>
              <div className="field">
                <label className="label">选择征集</label>
                <select className="input" value={pickedCollection ?? ""} onChange={(e) => void pickCollection(Number(e.target.value))}>
                  {collections.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
                </select>
              </div>
              {collectionDetail && collectionDetail.submissions && collectionDetail.submissions.length > 0 ? (
                <>
                  <div className="hint" style={{ marginBottom: 8 }}>勾选要导入的作品（任意状态均可，复制成独立副本）。</div>
                  {collectionDetail.submissions.map((s) => {
                    const on = pickedSubs.includes(s.id);
                    return (
                      <label key={s.id} className={"vote-opt" + (on ? " is-on" : "")} style={{ marginBottom: 6 }}>
                        <input type="checkbox" checked={on} onChange={() => setPickedSubs((cur) => on ? cur.filter((x) => x !== s.id) : [...cur, s.id])} />
                        <span className="vote-opt-text">{`@${s.submitter.username}`} · {s.files.length} 个文件</span>
                      </label>
                    );
                  })}
                  <button className="btn btn-primary btn-sm" onClick={() => void doImport()} disabled={busy || pickedSubs.length < 1}>导入 {pickedSubs.length} 件</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => setImportOpen(false)}>取消</button>
                </>
              ) : (
                <p className="muted">该征集暂无可见作品。</p>
              )}
            </>
          )}
        </div>
      )}
      {a.exhibits && a.exhibits.length > 0 ? (
        <>
          <div className="exhibit-grid">
            {a.exhibits.map((ex) => {
              const oid = ex.vote_option_id;
              const on = oid != null && selected.includes(oid);
              const mine = oid != null && mySel.includes(oid);
              const pct = total > 0 ? Math.round((ex.vote_count / total) * 100) : 0;
              return (
                <div key={ex.id} className={"exhibit-card" + (mine ? " is-mine" : "")}>
                  <div className="exhibit-media">{ex.files.map(renderExFile)}</div>
                  <div className="exhibit-title">{ex.title || "未命名"}</div>
                  {canVote ? (
                    <div className="exhibit-vote">
                      <button
                        type="button"
                        className={"vote-opt" + (on ? " is-on" : "")}
                        disabled={busy || (oid == null || (!on && selected.length >= a.max_choices_per_voter))}
                        onClick={() => oid != null && toggleOption(oid)}
                      >
                        {on ? "✓ 已选" : "投票"}
                      </button>
                    </div>
                  ) : votingActive ? (
                    <div className="exhibit-tally">
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <span>{ex.vote_count} 票</span>
                        <span className="muted">{pct}%</span>
                      </div>
                      <div style={{ height: 6, background: "#e5e7eb", borderRadius: 3, overflow: "hidden", marginTop: 3 }}>
                        <div style={{ width: `${pct}%`, height: "100%", background: "#2563eb" }} />
                      </div>
                      {mine && <div className="muted" style={{ marginTop: 2 }}>你投了这项</div>}
                    </div>
                  ) : null}
                  <div className="exhibit-rate">
                    <button className={"rate-btn" + (ex.my_rating === "like" ? " is-on like" : "")} onClick={() => doRate(ex.id, "like")} disabled={busy || a.status !== "open"}>👍 {ex.like_count}</button>
                    <button className={"rate-btn" + (ex.my_rating === "dislike" ? " is-on dislike" : "")} onClick={() => doRate(ex.id, "dislike")} disabled={busy || a.status !== "open"}>👎 {ex.dislike_count}</button>
                  </div>
                  {canManageExhibits && (
                    <div style={{ marginTop: 6, display: "flex", gap: 6 }}>
                      {canEditExhibit && <button className="btn btn-ghost btn-sm" onClick={() => void doUpdateExhibit(ex.id, ex.title)} disabled={busy}>改</button>}
                      <button className="btn btn-ghost btn-sm" onClick={() => void doDeleteExhibit(ex.id)} disabled={busy}>删</button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {canVote && (
            <div style={{ marginTop: 8 }}>
              <button className="btn btn-primary btn-sm" onClick={doVote} disabled={busy || selected.length < 1}>投票</button>
            </div>
          )}
          {votingActive && !canVote && <div className="muted" style={{ marginTop: 8 }}>共 {total} 人投票</div>}
          {votingActive && a.ballots && a.ballots.length > 0 && (
            <details style={{ marginTop: 12 }}>
              <summary className="muted">查看投票明细（{a.ballots.length}）</summary>
              <ul style={{ marginTop: 8 }}>
                {a.ballots.map((b) => {
                  const names = (a.exhibits || [])
                    .filter((ex) => ex.vote_option_id != null && b.option_ids.includes(ex.vote_option_id))
                    .map((ex) => ex.title || "未命名");
                  return (
                    <li key={b.id} style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 0" }}>
                      {b.voter ? (
                        <>
                          <Avatar user={b.voter} />
                          <span>{b.voter.nickname || b.voter.username}</span>
                        </>
                      ) : (
                        <>
                          <span className="avatar avatar--sm" style={{ background: "#d1d5db" }} aria-hidden="true" />
                          <span className="muted">游客</span>
                        </>
                      )}
                      <span className="muted">投：{names.join("、") || "—"}</span>
                    </li>
                  );
                })}
              </ul>
            </details>
          )}
          {votingActive && a.ballots === null && (
            <div className="alert alert-info" style={{ marginTop: 12 }}>
              <span>秘密投票 —— 个人投票明细不公开。</span>
            </div>
          )}
        </>
      ) : (
        <p className="empty-text">暂无展品。</p>
      )}
    </div>
  );
}
