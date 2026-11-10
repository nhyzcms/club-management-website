import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useLoginModal } from "../components/LoginModalProvider";

/** /profile → /u/<我的id>。需先取 me.id，所以是一个独立组件而不是静态 redirect。
 *  保留 query（如 ?tab=password）——安全验证回跳「完成即回原表单」依赖于此。 */
export default function ProfileRedirect() {
  const navigate = useNavigate();
  const location = useLocation();
  const { openLogin } = useLoginModal();
  useEffect(() => {
    api.me()
      .then((d: any) => navigate(`/u/${d.user.id}${location.search}`, { replace: true }))
      .catch(() => openLogin());
  }, [navigate, openLogin, location.search]);
  return null;
}
