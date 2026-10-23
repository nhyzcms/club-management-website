import { useEffect, useState } from "react";
import { api } from "../../api/client";
import MemberClaimForm from "../member/MemberClaimForm";
import { MEMBER_STATUS_LABELS, type MemberIdentityStatus } from "../../types/member";
import "../../styles/member.css";

/**
 * 「社员身份」面板（Part A / ADR-0025）：展示绑定状态与识别码；未绑定时可自助认领。
 *
 * 三种形态：已绑定（展示识别码）/ 未绑定且有候选（认领表单）/ 未绑定且无候选（说明）。
 */
export default function MemberIdentityPanel() {
  const [data, setData] = useState<MemberIdentityStatus | null>(null);
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState("");

  const load = () => {
    api.memberIdentity()
      .then((d: any) => setData(d as MemberIdentityStatus))
      .catch((e: any) => setErr(e.message || "加载失败"));
  };
  useEffect(load, []);

  if (err) {
    return (
      <div className="card card-pad">
        <h2 className="profile-panel-title">社员身份</h2>
        <p className="muted">{err}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="card card-pad">
        <h2 className="profile-panel-title">社员身份</h2>
        <p className="muted">加载中…</p>
      </div>
    );
  }

  const onClaimed = () => {
    setNotice("认领成功。");
    load();
  };

  return (
    <div className="card card-pad">
      <h2 className="profile-panel-title">社员身份</h2>
      {data.bound ? (
        <>
          {notice && <p className="member-claim-ok" role="status">{notice}</p>}
          <p className="muted">已绑定你的社员身份档案。</p>
          <div className="member-card">
            <div className="member-card-code">{data.bound.code}</div>
            <div className="member-card-meta">
              <span><strong>{data.bound.name}</strong></span>
              {data.bound.card_no && (
                <span className="muted">校牌号 {data.bound.card_no}</span>
              )}
              <span className="muted">
                第 {data.bound.cohort} 届
              </span>
              <span
                className={
                  "badge " + (data.bound.status === "active" ? "badge-success" : "badge-ghost")
                }
              >
                {MEMBER_STATUS_LABELS[data.bound.status] ?? data.bound.status}
              </span>
            </div>
          </div>
          <p className="muted">
            识别码用于工牌二维码核验；二维码由管理员统一导出制作。信息有误请联系信息组。
          </p>
        </>
      ) : !data.enabled ? (
        <p className="muted">自助认领当前已关闭。如果你是社员但尚未绑定，请联系管理员处理。</p>
      ) : data.candidates.length > 0 ? (
        <>
          <p className="muted">以下身份是否是你？选择一条并输入手机号后四位完成绑定。</p>
          <MemberClaimForm candidates={data.candidates} onDone={onClaimed} />
        </>
      ) : (
        <p className="muted">
          暂无可认领的身份。如果你确信自己是社员，可能名单尚未导入或姓名不一致，请联系信息组。
        </p>
      )}
    </div>
  );
}
