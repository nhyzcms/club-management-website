import "./Avatar.css";

interface AvatarUser {
  id: number;
  avatar: string | null;
  nickname?: string;
  username: string;
}

interface AvatarProps {
  user: AvatarUser;
  size?: "sm" | "md";
  className?: string;
}

/**
 * 用户头像。有图片则显示图片，否则显示昵称/用户名首字母的渐变圆。
 * 复用全局 --brand 主色，与 HomePage / UserProfile 的头像视觉保持一致。
 */
export default function Avatar({ user, size = "sm", className }: AvatarProps) {
  const initial = (user.nickname || user.username || "?").charAt(0).toUpperCase();
  const cls = `avatar avatar--${size}${className ? " " + className : ""}`;
  return (
    <span className={cls}>
      {user.avatar ? (
        <img src={user.avatar} alt="" width={size === "md" ? 32 : 24} height={size === "md" ? 32 : 24} />
      ) : (
        <span className="avatar-initial">{initial}</span>
      )}
    </span>
  );
}
