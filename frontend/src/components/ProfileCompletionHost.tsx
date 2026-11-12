import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { CARD_NO_IDENTITIES } from "../types/profile";
import { useLoginModal } from "./LoginModalProvider";
import ProfileCompletionModal from "./ProfileCompletionModal";

/**
 * 「下次一定」只在本次登录会话内生效：标记放 sessionStorage，不写服务端。
 * 为什么不做服务端已读：需求是「跳过也算没填，下次登录依旧提醒」——
 * 服务端台账会把提醒永久消掉，反而违背意图。
 */
const DISMISS_KEY = "nhyz.profilePrompt.dismissed";

/** sessionStorage 在隐私模式 / 部分 WebView 下会抛错，标记读写一律降级为「无标记」。 */
function readFlag(): boolean {
  try {
    return sessionStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}

function writeFlag(): void {
  try {
    sessionStorage.setItem(DISMISS_KEY, "1");
  } catch {
    /* 存不了就只在内存里静默（本次登录不重复弹，刷新后会再弹）。 */
  }
}

function clearFlag(): void {
  try {
    sessionStorage.removeItem(DISMISS_KEY);
  } catch {
    /* 同上 */
  }
}

/**
 * 资料里还缺哪些实名信息（取 `/auth/me/` 的 profile 快照）。
 *
 * - 真实姓名：空即缺（服务端对空姓名永远允许补录，所以补得上）；
 * - 校牌号：只有资料页真的会渲染这一栏、且本人能补录时才算缺——
 *   教师 / 家长 / 外校生不登记校牌号、已绑定名册的人由名册决定，
 *   这两种情况不该提醒（提醒了也改不了，会变成死循环）。
 */
export function missingProfileFields(profile: any): string[] {
  const out: string[] = [];
  if (!String(profile?.real_name ?? "").trim()) out.push("真实姓名");
  const identity = String(profile?.identity ?? "");
  const showsCardNo = !identity || CARD_NO_IDENTITIES.includes(identity);
  if (showsCardNo && profile?.card_no_editable && !String(profile?.card_no ?? "").trim()) {
    out.push("校牌号");
  }
  return out;
}

/** 已经站在本人的资料编辑页上（默认 tab 就是 profile）→ 不用再弹，弹了也是盖住表单。 */
function onOwnProfileEditPage(loc: { pathname: string; search: string }, userId: number | null): boolean {
  if (userId == null || loc.pathname !== `/u/${userId}`) return false;
  const tab = new URLSearchParams(loc.search).get("tab");
  return !tab || tab === "profile";
}

/**
 * 实名资料补全提醒的全局宿主（挂在 App 根部，桌面 / 手机版共用）。
 *
 * 触发：挂载 + 每次登录态变化（``authNonce``）后拉一次 `/auth/me/`；
 * 缺项且本次登录没点过「下次一定」→ 弹窗。登出（me 失败）时清掉标记，
 * 保证「登出再登录」或换设备登录都会重新提醒，直到资料补齐。
 */
export default function ProfileCompletionHost() {
  const { authNonce } = useLoginModal();
  const navigate = useNavigate();
  const location = useLocation();
  // 只在登录态变化时判定一次，所以位置用 ref 读「判定那一刻」的值，避免每次切页都重拉 /auth/me/。
  const locRef = useRef(location);
  locRef.current = location;
  const [missing, setMissing] = useState<string[]>([]);
  const [userId, setUserId] = useState<number | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let alive = true;
    setReady(false);
    api.me()
      .then((d: any) => {
        if (!alive) return;
        const rows = missingProfileFields(d?.profile);
        if (rows.length === 0) {
          // 资料齐了：标记没用了，清掉以免影响以后的判断。
          clearFlag();
          setMissing([]);
          return;
        }
        const id = d?.user?.id ?? null;
        setUserId(id);
        setMissing(readFlag() || onOwnProfileEditPage(locRef.current, id) ? [] : rows);
      })
      .catch(() => {
        if (!alive) return;
        // 未登录 / 会话失效：清标记，下次登录照弹。
        clearFlag();
        setMissing([]);
      });
    return () => {
      alive = false;
    };
  }, [authNonce]);

  // 让位给已在屏幕上的弹窗（登录框 / 账号有效期 / 挤号），避免两层遮罩叠在一起。
  useEffect(() => {
    if (missing.length === 0) {
      setReady(false);
      return;
    }
    const otherModalOpen = () => !!document.querySelector('[aria-modal="true"]');
    if (!otherModalOpen()) {
      setReady(true);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(() => {
      if (!otherModalOpen() || Date.now() - started > 15000) {
        window.clearInterval(timer);
        setReady(true);
      }
    }, 600);
    return () => window.clearInterval(timer);
  }, [missing]);

  const later = useCallback(() => {
    writeFlag();
    setMissing([]);
  }, []);

  const fill = useCallback(() => {
    // 不写标记：如果到了资料页又没填，至少刷新 / 下次登录还会提醒。
    setMissing([]);
    if (userId != null) navigate(`/u/${userId}?tab=profile`);
  }, [navigate, userId]);

  if (!ready || missing.length === 0) return null;
  return <ProfileCompletionModal missing={missing} onLater={later} onFill={fill} />;
}
