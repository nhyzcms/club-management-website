import { useCallback, useEffect, useRef, useState } from "react";
import { postcardAdminApi, POSTCARD_GRADES, type StatsPayload } from "../../../api/postcardAdmin";
import { errMessage, isForbidden } from "./pure";

/**
 * 总数据统计：指标卡 + 三张图（寄达校 / 年级 / 时间线）。
 *
 * chart.js 走动态 import：只在管理员打开统计页时加载（约 60KB gzip），
 * 普通用户首屏不受影响（2C2G 服务器 / 3M 带宽约束）。
 */
export default function StatsTab() {
  const [data, setData] = useState<StatsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const schoolRef = useRef<HTMLCanvasElement | null>(null);
  const gradeRef = useRef<HTMLCanvasElement | null>(null);
  const dayRef = useRef<HTMLCanvasElement | null>(null);
  const chartsRef = useRef<any[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await postcardAdminApi.stats());
    } catch (e) {
      setError(isForbidden(e) ? "需要 manage_postcard 权限。" : errMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!data) return;
    let cancelled = false;
    const built: any[] = [];

    const draw = async () => {
      const mod: any = await import("chart.js/auto");
      const Chart = mod.Chart ?? mod.default;
      if (cancelled) return;
      // 取图表容器的最终计算色（自定义属性里的 var() 不能被 canvas 解析）。
      const probe = schoolRef.current?.parentElement ?? document.body;
      const ink = getComputedStyle(probe).color || "#111827";
      const grid = "rgba(128,128,128,0.18)";
      const base = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: ink } } },
        scales: {
          x: { ticks: { color: ink }, grid: { color: grid } },
          y: { ticks: { color: ink }, grid: { color: grid }, beginAtZero: true },
        },
      } as const;

      const top = data.by_school.slice(0, 12);
      if (schoolRef.current) {
        built.push(
          new Chart(schoolRef.current, {
            type: "bar",
            data: {
              labels: top.map((s) => s.school || "（未填）"),
              datasets: [
                { label: "已登记", data: top.map((s) => s.total), backgroundColor: "rgba(59,130,246,0.55)" },
                { label: "已报寄", data: top.map((s) => s.reported), backgroundColor: "rgba(16,185,129,0.65)" },
              ],
            },
            options: { ...base, indexAxis: "y" },
          }),
        );
      }
      if (gradeRef.current) {
        built.push(
          new Chart(gradeRef.current, {
            type: "doughnut",
            data: {
              labels: data.by_grade.map(
                (g) => POSTCARD_GRADES.find((x) => x.value === g.grade)?.label || g.grade,
              ),
              datasets: [
                {
                  data: data.by_grade.map((g) => g.total),
                  backgroundColor: ["rgba(59,130,246,0.7)", "rgba(168,85,247,0.7)", "rgba(245,158,11,0.7)"],
                },
              ],
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: { legend: { labels: { color: ink } } },
            },
          }),
        );
      }
      if (dayRef.current) {
        built.push(
          new Chart(dayRef.current, {
            type: "line",
            data: {
              labels: data.by_day.map((d) => d.day || "—"),
              datasets: [
                {
                  label: "每日登记量",
                  data: data.by_day.map((d) => d.total),
                  borderColor: "rgba(59,130,246,0.9)",
                  backgroundColor: "rgba(59,130,246,0.18)",
                  fill: true,
                  tension: 0.3,
                },
              ],
            },
            options: base,
          }),
        );
      }
      chartsRef.current = built;
    };

    void draw();
    return () => {
      cancelled = true;
      chartsRef.current.forEach((c) => c?.destroy?.());
      chartsRef.current = [];
    };
  }, [data]);

  if (loading) return <p className="pa-muted">加载中…</p>;

  return (
    <div className="pa-stack">
      {error && <p className="pa-error">{error}</p>}
      {data && (
        <>
          <div className="pa-stat-cards">
            <div className="pa-stat">
              <span className="pa-stat-num tnum">{data.items.total}</span>
              <span className="pa-muted">明信片总数</span>
            </div>
            <div className="pa-stat">
              <span className="pa-stat-num tnum">{data.items.reported}</span>
              <span className="pa-muted">已报寄</span>
            </div>
            <div className="pa-stat">
              <span className="pa-stat-num tnum">{data.destination_schools}</span>
              <span className="pa-muted">寄达校</span>
            </div>
            <div className="pa-stat">
              <span className="pa-stat-num tnum">{data.registrations.total}</span>
              <span className="pa-muted">登记单</span>
            </div>
          </div>
          <p className="pa-hint">
            登记单：已登记 {data.registrations.registered} · 已报寄 {data.registrations.reported} · 已取消{" "}
            {data.registrations.cancelled}
          </p>

          <section className="pa-card">
            <h3 className="pa-card-title">寄达校 Top 12</h3>
            <div className="pa-chart pa-chart-tall">
              <canvas ref={schoolRef} />
            </div>
          </section>
          <div className="pa-grid2">
            <section className="pa-card">
              <h3 className="pa-card-title">年级分布</h3>
              <div className="pa-chart">
                <canvas ref={gradeRef} />
              </div>
            </section>
            <section className="pa-card">
              <h3 className="pa-card-title">每日登记量</h3>
              <div className="pa-chart">
                <canvas ref={dayRef} />
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
