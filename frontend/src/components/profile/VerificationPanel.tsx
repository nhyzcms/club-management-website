import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { EMAIL_DOMAIN_BLOCKED_MESSAGE } from "../../api/shared";
import { useSitePolicy } from "../../api/sitePolicy";
import { IDENTITY_OPTIONS } from "../../types/profile";
import NoticeModal from "../NoticeModal";
import "../../styles/profile.css";

// 前后端契约（#36）：通道集 + 通道对象键集，与后端 /auth/verification/ 对齐
// （accounts.tests_verification.VerificationPanelContractTest 钉死，防漂移）。
export const VERIFICATION_CHANNELS = ["appointment", "email", "manual", "authcode"];
export const VERIFICATION_CARD_FIELDS = ["channel", "status", "identifier", "verified_at"];

type ChannelStatus = "none" | "pending" | "approved" | "rejected";

interface ChannelCard {
  channel: string;
  status: ChannelStatus;
  identifier: string;
  verified_at: string | null;
}

interface VerificationStatus {
  is_verified: boolean;
  channels: ChannelCard[];
}

// 后台委任对普通人不可申请：status=none 不铺卡，避免空通道占位。委任通过后才显示。
function visibleChannel(card: ChannelCard) {
  return !(card.channel === "appointment" && card.status === "none");
}

const CHANNEL_META: Record<string, { label: string; desc: string }> = {
  appointment: {
    label: "后台委任",
    desc: "后台将账号委任为管理员或超级管理员时，身份即视为已验证，无需再走邮箱或人工通道。",
  },
  email: { label: "邮箱验证", desc: "绑定并验证一个邮箱即可成为已验证用户。" },
  manual: { label: "人工审批", desc: "提交身份证明，由管理员审核通过即成为已验证用户。" },
  authcode: { label: "认证码", desc: "持有管理员发放的认证码时，输入码即可完成验证。" },
};

// 各通道各状态 → 展示文案 + 徽章 + 提示（数据驱动：加状态只改此处）。
const STATE: Record<string, Record<ChannelStatus, { label: string; badge: string; hint: string }>> = {
  appointment: {
    none: { label: "未委任", badge: "badge-ghost", hint: "此通道由后台委任，无法自行申请。" },
    pending: { label: "待委任", badge: "badge-warning", hint: "" },
    approved: { label: "已委任", badge: "badge-success", hint: "身份已由后台委任确认，无需再验证。" },
    rejected: { label: "已撤销", badge: "badge-danger", hint: "" },
  },
  email: {
    none: { label: "未绑定", badge: "badge-ghost", hint: "绑定邮箱后可用邮箱登录、找回密码。" },
    pending: { label: "待验证", badge: "badge-warning", hint: "验证邮件已发送，请查收并点击验证链接。" },
    approved: { label: "已通过", badge: "badge-success", hint: "邮箱已验证。" },
    rejected: { label: "已驳回", badge: "badge-danger", hint: "" }, // email 通道无驳回，保留数据驱动完备性
  },
  manual: {
    none: { label: "未提交", badge: "badge-ghost", hint: "提交身份证明（学生证照片等），由管理员审核。" },
    pending: { label: "审核中", badge: "badge-warning", hint: "身份证明已提交，等待管理员审核。" },
    approved: { label: "已通过", badge: "badge-success", hint: "身份审核已通过。" },
    rejected: { label: "已驳回", badge: "badge-danger", hint: "身份证明被驳回，可重新提交。" },
  },
  authcode: {
    none: { label: "未使用", badge: "badge-ghost", hint: "输入收到的认证码即可完成验证。" },
    pending: { label: "待兑换", badge: "badge-warning", hint: "" }, // 该通道无 pending，保留数据驱动完备性
    approved: { label: "已通过", badge: "badge-success", hint: "认证码已验证。" },
    rejected: { label: "已撤销", badge: "badge-danger", hint: "" }, // 该通道无 rejected，保留数据驱动完备性
  },
};

function CardShell({ card, children }: { card: ChannelCard; children?: React.ReactNode }) {
  const meta = CHANNEL_META[card.channel] ?? { label: card.channel, desc: "" };
  const st = (STATE[card.channel] ?? STATE.manual)[card.status];
  const showPendingId = card.channel === "email" && card.status === "pending" && card.identifier;
  const showBoundId = card.channel === "email" && card.status === "approved" && card.identifier;
  const appointmentLabel = card.identifier === "superuser" ? "超级管理员" : "管理员";
  const showAppointmentId = card.channel === "appointment" && card.status === "approved" && card.identifier;
  return (
    <div className={"verify-card verify-card-" + card.status}>
      <div className="verify-card-head">
        <span className="verify-card-label">{meta.label}</span>
        <span className={"badge " + st.badge}>{st.label}</span>
      </div>
      {meta.desc && <p className="muted verify-card-desc">{meta.desc}</p>}
      {showPendingId && <p className="muted verify-card-id">待验证邮箱：{card.identifier}</p>}
      {showBoundId && <p className="muted verify-card-id">已绑定：{card.identifier}</p>}
      {showAppointmentId && <p className="muted verify-card-id">委任身份：{appointmentLabel}</p>}
      {st.hint && <p className="muted verify-card-hint">{st.hint}</p>}
      {children}
    </div>
  );
}

function EmailCard({ card, onChanged, closed }: { card: ChannelCard; onChanged: () => void; closed: boolean }) {
  const [emailInput, setEmailInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  // 邮箱后缀不在白名单（ADR-0023）：后端回专属 reason，这里弹窗打断（不做行内小字）。
  const [domainBlocked, setDomainBlocked] = useState(false);

  if (closed) return <CardShell card={card} />;

  const bind = (email: string) => {
    if (!email) return;
    setSubmitting(true);
    setErr("");
    setMsg("");
    api.verificationEmailBind(email)
      .then(() => {
        setMsg("验证邮件已发送，请查收。");
        setEmailInput("");
        onChanged();
      })
      .catch((e: any) => {
        if (e?.apiError?.kind === "email_domain_not_allowed") {
          setDomainBlocked(true);
          return;
        }
        setErr(e.message || "操作失败");
      })
      .finally(() => setSubmitting(false));
  };

  const primaryLabel = card.status === "none" ? "绑定邮箱" : "换绑邮箱";

  return (
    <CardShell card={card}>
      <p className="muted verify-card-hint">
        仅支持网易邮箱（163 / 126 / yeah.net）、QQ 邮箱、微软 Outlook、苹果 iCloud（含「隐藏我的邮件」）、
        三大运营商（移动 / 联通 / 电信）、新浪邮箱，以及中国高校校园邮箱（.edu.cn / .edu.hk / .edu.mo / .edu.tw）。
      </p>
      <div className="verify-card-actions">
        {card.status === "pending" && (
          <button className="btn btn-sm" type="button" disabled={submitting}
                  onClick={() => bind(card.identifier)}>重发验证邮件</button>
        )}
        <div className="verify-email-form">
          <input type="email" inputMode="email" placeholder="email@example.com"
                 value={emailInput} disabled={submitting}
                 onChange={(e) => setEmailInput(e.target.value)} />
          <button className="btn btn-sm btn-primary" type="button"
                  disabled={submitting || !emailInput}
                  onClick={() => bind(emailInput)}>{primaryLabel}</button>
        </div>
      </div>
      {msg && <p className="muted verify-card-msg">{msg}</p>}
      {err && <p className="verify-card-err">{err}</p>}
      {domainBlocked && (
        <NoticeModal
          message={EMAIL_DOMAIN_BLOCKED_MESSAGE}
          onClose={() => setDomainBlocked(false)}
        />
      )}
    </CardShell>
  );
}

function ManualCard({ card, onChanged, closed }: { card: ChannelCard; onChanged: () => void; closed: boolean }) {
  const [realName, setRealName] = useState("");
  const [identity, setIdentity] = useState("");
  const [files, setFiles] = useState<FileList | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const canSubmit = !closed && (card.status === "none" || card.status === "rejected");
  if (!canSubmit) return <CardShell card={card} />;

  const submit = () => {
    if (!realName || !identity || !files || files.length === 0) return;
    const fd = new FormData();
    fd.append("real_name", realName);
    fd.append("identity", identity);
    Array.from(files).forEach((f) => fd.append("proof_files", f));
    setSubmitting(true);
    setErr("");
    setMsg("");
    api.verificationManualSubmit(fd)
      .then(() => {
        setMsg("身份证明已提交，等待管理员审核。");
        setRealName("");
        setIdentity("");
        setFiles(null);
        onChanged();
      })
      .catch((e: any) => setErr(e.message || "提交失败"))
      .finally(() => setSubmitting(false));
  };

  const label = card.status === "rejected" ? "重新提交" : "提交身份证明";
  return (
    <CardShell card={card}>
      <div className="verify-manual-form">
        <input type="text" placeholder="真实姓名" value={realName} disabled={submitting}
               onChange={(e) => setRealName(e.target.value)} />
        <select className="verify-manual-identity" value={identity} disabled={submitting}
                onChange={(e) => setIdentity(e.target.value)}>
          <option value="" disabled>请选择身份</option>
          {IDENTITY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <div className="verify-manual-upload">
          <label className="verify-manual-upload-label">学生证或其他证明材料（敏感信息可打码）</label>
          <input type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={submitting}
                 onChange={(e) => setFiles(e.target.files)} />
          <p className="muted verify-manual-privacy">
            我们重视你的信息安全：证明材料存于私有存储，仅本人与审核员可见，仅用于身份核验。
          </p>
        </div>
        <button className="btn btn-sm btn-primary" type="button"
                disabled={submitting || !realName || !identity || !files || files.length === 0}
                onClick={submit}>{label}</button>
      </div>
      {msg && <p className="muted verify-card-msg">{msg}</p>}
      {err && <p className="verify-card-err">{err}</p>}
    </CardShell>
  );
}

function CodeCard({ card, onChanged, closed }: { card: ChannelCard; onChanged: () => void; closed: boolean }) {
  const [codeInput, setCodeInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  // 只能兑换、不能生成：码由管理员在 Django 后台生成并线下分发（ADR-0020）。
  const canRedeem = !closed && card.status === "none";
  if (!canRedeem) return <CardShell card={card} />;

  const redeem = () => {
    if (!codeInput.trim()) return;
    setSubmitting(true);
    setErr("");
    setMsg("");
    api.verificationAuthcodeRedeem(codeInput)
      .then(() => {
        setMsg("认证码验证通过，账号已完成验证。");
        setCodeInput("");
        onChanged();
      })
      .catch((e: any) => setErr(e.message || "兑换失败"))
      .finally(() => setSubmitting(false));
  };

  return (
    <CardShell card={card}>
      <div className="verify-card-actions">
        <div className="verify-email-form">
          <input type="text" placeholder="输入认证码" value={codeInput} disabled={submitting}
                 autoComplete="off" spellCheck={false}
                 onChange={(e) => setCodeInput(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") redeem(); }} />
          <button className="btn btn-sm btn-primary" type="button"
                  disabled={submitting || !codeInput.trim()}
                  onClick={redeem}>兑换</button>
        </div>
      </div>
      {msg && <p className="muted verify-card-msg">{msg}</p>}
      {err && <p className="verify-card-err">{err}</p>}
    </CardShell>
  );
}

export default function VerificationPanel() {
  const [data, setData] = useState<VerificationStatus | null>(null);
  const [err, setErr] = useState("");
  const policy = useSitePolicy();

  const load = () => {
    api.verificationStatus()
      .then((d: any) => setData(d as VerificationStatus))
      .catch((e: any) => setErr(e.message || "加载失败"));
  };
  useEffect(load, []);

  if (err) {
    return (
      <div className="card card-pad">
        <h2 className="profile-panel-title">账号验证</h2>
        <p className="muted">{err}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="card card-pad">
        <h2 className="profile-panel-title">账号验证</h2>
        <p className="muted">加载中…</p>
      </div>
    );
  }

  return (
    <div className="card card-pad">
      <h2 className="profile-panel-title">账号验证</h2>
      <p className="muted verify-overview">
        {data.is_verified
          ? "你的账号已验证。"
          : "你的账号尚未验证（访客）——完成下列任一通道即成为已验证用户，解锁发帖 / 发消息 / 建申报等。"}
      </p>
      {!policy.verification_enabled && (
        <p className="muted verify-overview">验证通道已关闭</p>
      )}
      <div className="verify-cards">
        {data.channels.filter(visibleChannel).map((c) => {
          if (c.channel === "email") {
            return <EmailCard key={c.channel} card={c} onChanged={load} closed={!policy.verification_enabled} />;
          }
          if (c.channel === "manual") {
            return <ManualCard key={c.channel} card={c} onChanged={load} closed={!policy.verification_enabled} />;
          }
          if (c.channel === "authcode") {
            return <CodeCard key={c.channel} card={c} onChanged={load} closed={!policy.verification_enabled} />;
          }
          return <CardShell key={c.channel} card={c} />;
        })}
      </div>
    </div>
  );
}
