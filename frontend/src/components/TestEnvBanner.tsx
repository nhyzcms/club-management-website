import { PRODUCTION_URL } from "../constants";
import "./TestEnvBanner.css";

/**
 * test 环境常驻横幅。
 *
 * 环境标识由 `/version/` 的 `environment` 字段运行时下发（同一个镜像跑生产和
 * test，不能靠构建期常量）。未加载完或生产环境时不渲染——宁可不显示，也不能
 * 在正式站误报「测试环境」。
 *
 * embed 模式（后台 iframe）隐藏：那里空间宝贵，且操作者已经在后台语境里。
 */
export default function TestEnvBanner({
  environment,
  hidden = false,
}: {
  environment?: string;
  hidden?: boolean;
}) {
  if (hidden || environment !== "test") return null;
  return (
    <div className="test-env-banner" role="status">
      <span className="test-env-badge">TEST</span>
      <span className="test-env-text">测试环境 · 数据与生产隔离 · 请勿录入真实数据</span>
      <a className="test-env-link" href={PRODUCTION_URL}>
        返回生产 →
      </a>
    </div>
  );
}
