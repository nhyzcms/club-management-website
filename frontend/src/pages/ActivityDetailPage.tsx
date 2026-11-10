import { useState, useEffect } from "react";
import { useParams, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { activityApi } from "../api/activities";
import type { ActivityDetail } from "../types/activities";
import PageChrome from "../components/PageChrome";
import { useEmbedMode } from "../embed";
import { useLoginModal } from "../components/LoginModalProvider";
import ActivityDetailShell from "./activity/ActivityDetailShell";
import type { ActivityViewer } from "./activity/types";

export default function ActivityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const { openLogin, authNonce } = useLoginModal();
  const embed = useEmbedMode();
  const [activity, setActivity] = useState<ActivityDetail | null>(null);
  const [user, setUser] = useState<ActivityViewer | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [loadStatus, setLoadStatus] = useState<number>(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.me().then((d) => setUser({ id: d.user.id, can_review_collections: d.user.permissions?.can_review_collections, can_change_activity: d.user.permissions?.can_change_activity })).catch(() => setUser(null));
  }, [authNonce]);

  useEffect(() => {
    if (!id) return;
    setLoadError("");
    setLoadStatus(0);
    setActivity(null);
    activityApi.get(Number(id))
      .then(setActivity)
      .catch((err: { message?: string; status?: number }) => {
        setLoadError(err.message || "加载失败");
        setLoadStatus(err.status || 0);
      });
  }, [id, authNonce]);

  if (!activity) {
    if (user === undefined || !loadError) {
      return <PageChrome><div className="container" style={{ padding: "var(--s-16)" }}><p className="muted">加载中…</p></div></PageChrome>;
    }
    const needLogin = !embed && !user && (loadStatus === 404 || loadStatus === 403);
    return (
      <PageChrome>
        <div className="container" style={{ padding: "var(--s-16)" }}>
          {needLogin ? (
            <div className="card card-pad">
              <h2 style={{ margin: "0 0 var(--s-3)" }}>需要登录</h2>
              <p className="muted" style={{ marginBottom: "var(--s-4)" }}>
                该活动仅登录成员可见。众议、征集、展示及仅成员调研需登录后查看。
              </p>
              <button className="btn btn-primary" onClick={() => openLogin(location.pathname + location.search)}>登录</button>
            </div>
          ) : (
            <div className="alert alert-danger"><span>{loadError}</span></div>
          )}
        </div>
      </PageChrome>
    );
  }

  return (
    <ActivityDetailShell
      a={activity}
      setActivity={setActivity}
      user={user}
      error={error}
      setError={setError}
      busy={busy}
      setBusy={setBusy}
    />
  );
}
