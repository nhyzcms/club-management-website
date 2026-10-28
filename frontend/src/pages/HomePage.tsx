import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { newsApi } from "../api/news";
import { aboutApi, type ClubOverview } from "../api/about";
import AppShell from "../components/AppShell";
import ClubFeed from "../components/ClubFeed";
import NeonParticles from "../components/NeonParticles";
import { useLoginModal } from "../components/LoginModalProvider";
import "../styles/form.css";
import "../styles/home.css";
import "../styles/about.css";

interface User {
  id: number;
  username: string;
  can_edit_about?: boolean;
}


const EqBars = () => (
  <span className="eq" aria-hidden="true"><span /><span /><span /><span /></span>
);

export default function HomePage() {
  const [user, setUser] = useState<User | null>(null);
  const [overview, setOverview] = useState<{ members: number; works: number } | null>(null);
  const [club, setClub] = useState<ClubOverview | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ founded: "", advisor: "", intro: "" });
  const navigate = useNavigate();
  const { openLogin, authNonce } = useLoginModal();

  useEffect(() => {
    document.title = "南汇一中 · 传媒社";
    api.me()
      .then((data) => setUser({
        id: data.user.id,
        username: data.user.username,
        can_edit_about: data.user.permissions?.can_edit_about,
      }))
      .catch(() => setUser(null));
  }, [authNonce]);

  useEffect(() => {
    newsApi.overview()
      .then(setOverview)
      .catch(() => setOverview(null));
    aboutApi.getOverview()
      .then(setClub)
      .catch(() => setClub(null));
  }, []);

  const go = (path: string) => {
    if (user) navigate(path);
    else openLogin(path);
  };

  const saveOverview = async () => {
    const updated = await aboutApi.updateOverview(draft);
    setClub(updated);
    setEditing(false);
  };

  return (
    <AppShell>
      <section className="hero">
        <NeonParticles className="hero-particles" />
        <div className="hero-inner">
          <span className="hero-badge"><EqBars /> 上海市南汇第一中学 · 传媒社</span>
          <h1>用镜头记录青春<br /><span className="accent">以创新展望未来</span></h1>
          <p className="hero-sub">校园影像、新媒体作品的策展窗口；加入社团、社团动态与活动申报，一站式直达。</p>
          <div className="hero-actions">
            <button className="btn btn-primary btn-lg" type="button" onClick={() => navigate("/join")}>
              加入社团
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
            </button>
            <button className="btn btn-ghost btn-lg" type="button" onClick={() => navigate("/activity")}>浏览动态</button>
          </div>
          <div className="quick-strip">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/activity"); }}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16v12H7l-3 3z" /></svg> 活动申报
            </a>
            <a href="#" onClick={(e) => { e.preventDefault(); go("/tasks"); }}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 11l2 2 4-4" /><rect x="4" y="5" width="16" height="16" rx="2" /><path d="M9 3v4M15 3v4" /></svg> 任务
            </a>
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/activity"); }}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2l2.4 6.9H22l-6 4.4 2.3 7L12 16l-6.3 4.3L8 13.3 2 8.9h7.6z" /></svg> 提交建议
            </a>
          </div>
        </div>
      </section>

      <div className="container">
        <div className="home-grid">
          <aside className="mascot-rail">
            <div className="rail-card">
              <h4>
                <span className="bar" /> 社团概览
                {user?.can_edit_about && !editing && (
                  <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }} type="button"
                          onClick={() => {
                            setDraft({
                              founded: club?.founded || "",
                              advisor: club?.advisor || "",
                              intro: club?.intro || "",
                            });
                            setEditing(true);
                          }}>编辑</button>
                )}
              </h4>
              {editing ? (
                <div className="form-stack">
                  <input className="input" value={draft.founded} onChange={(e) => setDraft({ ...draft, founded: e.target.value })} placeholder="成立" />
                  <input className="input" value={draft.advisor} onChange={(e) => setDraft({ ...draft, advisor: e.target.value })} placeholder="指导" />
                  <input className="input" value={draft.intro} onChange={(e) => setDraft({ ...draft, intro: e.target.value })} placeholder="简介" />
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="btn btn-primary btn-sm" type="button" onClick={saveOverview}>保存</button>
                    <button className="btn btn-ghost btn-sm" type="button" onClick={() => setEditing(false)}>取消</button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="stat-row"><span className="k">成立</span><span className="v tnum">{club?.founded || "—"}</span></div>
                  <div className="stat-row"><span className="k">成员</span><span className="v tnum">{overview ? overview.members : "—"}</span></div>
                  <div className="stat-row"><span className="k">指导</span><span className="v">{club?.advisor || "—"}</span></div>
                  <div className="stat-row"><span className="k">作品</span><span className="v tnum">{overview ? overview.works : "—"}</span></div>
                  {club?.intro && <p className="detail-sub" style={{ marginTop: 8 }}>{club.intro}</p>}
                </>
              )}
            </div>
            <div className="rail-card">
              <h4><span className="bar" /> 小工具</h4>
              <div className="widget-links">
                <button className="btn btn-secondary btn-sm" type="button" onClick={() => navigate("/exam")}>考试看板</button>
                <button className="btn btn-ghost btn-sm" type="button" onClick={() => navigate("/tutorials")}>教程集锦</button>
                <button className="btn btn-ghost btn-sm" type="button" onClick={() => navigate("/schedule")}>课表下载</button>
              </div>
            </div>
            <div className="rail-card rail-actions">
              <h4><span className="bar" /> 快速入口</h4>
              <button className="btn btn-secondary btn-sm" type="button" onClick={() => go("/activity/new")}>提交活动申报</button>
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => go("/tasks")}>我的任务</button>
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => navigate("/activity")}>浏览活动申报</button>
            </div>
          </aside>

          <div className="home-main">
            <ClubFeed user={user} />
          </div>
        </div>
      </div>
    </AppShell>
  );
}
