const STORAGE_KEY = "device_id";

/** 访客问卷去重用的浏览器侧标识（UUID，落 localStorage）。不是硬件 ID。 */
export function getDeviceId(): string {
  try {
    let id = localStorage.getItem(STORAGE_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(STORAGE_KEY, id);
    }
    return id;
  } catch {
    return crypto.randomUUID();
  }
}
