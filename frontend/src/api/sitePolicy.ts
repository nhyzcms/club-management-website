import { useEffect, useState } from "react";
import { createRequest } from "./shared";

const request = createRequest("");

/**
 * 公开策略快照的字段集合。
 *
 * **这是后端 allowlist 的前端镜像**（`common/views.py: PUBLIC_POLICY_FIELDS`
 * + Turnstile 两字段）。服务器只下发这些键，多出来的字段不会到前端——
 * 需要新字段时三处同改：后端 allowlist、`common/tests/test_public_policy.py`
 * 的冻结清单、这里。
 *
 * 运维参数（更新窗口、tus 上限、各条 per-IP 限流阈值）不再公开，
 * 管理员在 Django 后台的「频控策略 / 更新策略」里查看。
 */
export interface SitePolicy {
  verification_enabled: boolean;
  verification_valid_days: number;
  admin_valid_days: number;
  registration_verify_days: number;
  registration_enabled: boolean;
  comments_enabled: boolean;
  comment_max_depth: number;
  dms_enabled: boolean;
  sync_upload_max_bytes: number;
  turnstile_enabled: boolean;
  turnstile_site_key: string;
}

const DEFAULTS: SitePolicy = {
  verification_enabled: true,
  verification_valid_days: 365,
  admin_valid_days: 730,
  registration_verify_days: 60,
  registration_enabled: true,
  comments_enabled: true,
  comment_max_depth: 8,
  dms_enabled: true,
  sync_upload_max_bytes: 50 * 1024 * 1024,
  turnstile_enabled: false,
  turnstile_site_key: "",
};

let snapshot: SitePolicy = DEFAULTS;
let hydrated = false;
const listeners = new Set<() => void>();

export function getSitePolicy(): SitePolicy {
  return snapshot;
}

function notify() {
  listeners.forEach((fn) => fn());
}

export function subscribeSitePolicy(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function useSitePolicy(): SitePolicy {
  const [policy, setPolicy] = useState(snapshot);
  useEffect(() => subscribeSitePolicy(() => setPolicy(getSitePolicy())), []);
  return policy;
}

export function useSitePolicyReady(): boolean {
  const [ready, setReady] = useState(hydrated);
  useEffect(() => {
    setReady(hydrated);
    return subscribeSitePolicy(() => setReady(hydrated));
  }, []);
  return ready;
}

export function fetchSitePolicy(): Promise<void> {
  return request<SitePolicy>("/site-policy/")
    .then((data) => {
      snapshot = { ...DEFAULTS, ...data };
      notify();
    })
    .catch(() => {
      // Keep defaults if the public endpoint is unreachable.
    })
    .finally(() => {
      if (!hydrated) {
        hydrated = true;
        notify();
      }
    });
}
