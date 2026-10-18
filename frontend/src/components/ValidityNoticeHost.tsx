import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { VALIDITY_CHANGED_EVENT, type ValiditySummary } from "../utils/validity";
import { useLoginModal } from "./LoginModalProvider";
import ValidityNoticeModal from "./ValidityNoticeModal";

/**
 * 账号有效期弹窗的全局宿主（挂在 App 根部，桌面 / 手机版都覆盖）。
 *
 * 触发时机：
 * - 登录态变化（``authNonce``：登录 / 注册成功 / 登出）后拉一次快照；
 * - 认证通过（邮箱 / 认证码 / 人工审核通过后回到站点）dispatch ``VALIDITY_CHANGED_EVENT``。
 *
 * 是否弹窗由服务端 ``notice_pending`` 决定（``Profile.validity_notice_ack`` 记录已读的
 * 状态快照键），所以同一状态只弹一次、跨设备一致；关掉弹窗即写回。
 */
export default function ValidityNoticeHost() {
  const { authNonce } = useLoginModal();
  const [data, setData] = useState<ValiditySummary | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(() => {
    api.accountValidity()
      .then((d: any) => {
        const summary = d as ValiditySummary;
        setData(summary);
        setOpen(!!summary.notice_pending);
      })
      .catch(() => {
        // 未登录 / 网络失败：静默（这是提示，不是功能门禁）。
        setOpen(false);
      });
  }, []);

  useEffect(() => { load(); }, [load, authNonce]);

  useEffect(() => {
    const onChanged = () => load();
    window.addEventListener(VALIDITY_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(VALIDITY_CHANGED_EVENT, onChanged);
  }, [load]);

  const close = () => {
    setOpen(false);
    const key = data?.key;
    if (!key) return;
    // 写「已读」失败不影响体验：下次进入会再弹一次。
    api.accountValidityAck(key).catch(() => {});
  };

  if (!open || !data) return null;
  return <ValidityNoticeModal data={data} onClose={close} />;
}
