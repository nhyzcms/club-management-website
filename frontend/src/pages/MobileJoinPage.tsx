import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { recruitmentApi } from "../api/recruitment";
import MobileTabBar from "../components/MobileTabBar";
import "../styles/mobile.css";

/** 手机版加入社团（/m/join）：招生公告 + 阅读确认 → 自我介绍问卷。 */
export default function MobileJoinPage() {
  const navigate = useNavigate();
  const [content, setContent] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [ack, setAck] = useState(false);

  useEffect(() => {
    document.title = "加入社团 · 南汇一中传媒社";
    recruitmentApi
      .landing()
      .then((d) => setContent(d.notice.content || ""))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  return (
    <div className="m-app">
      <header className="m-topbar">
        <div className="m-brand">加入社团</div>
      </header>

      <div className="m-detail">
        {content ? (
          <div className="m-detail-body" dangerouslySetInnerHTML={{ __html: content }} />
        ) : (
          <p className="m-empty">{loaded ? "招生公告即将发布。" : "加载中…"}</p>
        )}

        <label className="m-check-row">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>我已阅读并知晓公告内容</span>
        </label>

        <button
          className="m-btn-primary"
          disabled={!ack}
          onClick={() => {
            sessionStorage.setItem("join_notice_ack", "1");
            navigate("/m/join/form");
          }}
        >
          立即加入
        </button>
      </div>

      <MobileTabBar />
    </div>
  );
}
