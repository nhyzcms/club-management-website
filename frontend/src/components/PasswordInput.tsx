import { useState, type ComponentPropsWithRef } from "react";

/**
 * 密码输入框 —— cobalt 的 .input-affix 之上叠加「显示/隐藏密码」眼睛按钮。
 * 显隐状态由组件内部自管；其余输入属性（含 ref）透传给底层 <input>。
 * 供 登录框 / 重置密码 / 个人中心改密 等所有密码字段复用，保证视觉与交互一致。
 */
export default function PasswordInput({ ref, ...props }: ComponentPropsWithRef<"input">) {
  const [show, setShow] = useState(false);
  return (
    <div className="input-affix">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>
      <input ref={ref} {...props} className="input" type={show ? "text" : "password"} />
      <button className="affix-btn" type="button" aria-label={show ? "隐藏密码" : "显示密码"} onClick={() => setShow((v) => !v)}>
        {show ? (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-10-8-10-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 10 8 10 8a18.5 18.5 0 0 1-2.16 3.19M1 1l22 22" /></svg>
        ) : (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" /><circle cx="12" cy="12" r="3" /></svg>
        )}
      </button>
    </div>
  );
}
