import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Card, Empty, fmtNumber, PageHeader, Reveal, SectionTitle, Spinner, Stagger, StaggerItem, StatCard } from "../components/ui";
import { Icon } from "../components/icons";

type AnalyticsData = {
  totals: { videos: number; views: number; likes: number; comments: number };
  series: { day: string; views: number; likes: number }[];
  best: { title: string; views: number; likes: number; comments: number; youtube_video_id: string; published_at: string | null }[];
  per_hour: { hour: string; videos: number; avg_views: number }[];
  queue_stats: Record<string, number>;
  source: string;
};

const PIE_COLORS = ["#8b5cf6", "#22d3ee", "#34d399", "#fbbf24", "#fb7185", "#a78bfa", "#38bdf8"];

const TOOLTIP_STYLE = {
  background: "#0f131d",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 12,
  fontSize: 11,
  padding: "8px 10px",
  boxShadow: "0 18px 40px -20px rgba(0,0,0,0.9)",
} as const;

export default function Analytics() {
  const { notify, subscribe } = useApp();
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      setData(await api.get<AnalyticsData>("/api/analytics"));
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load analytics");
    }
  }

  useEffect(() => {
    void load();
    const unsub = subscribe((e) => {
      if (e.type === "upload_done") void load();
    });
    return unsub;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function sync() {
    setBusy("sync");
    try {
      const res = await api.post<{ synced: number }>("/api/published/sync");
      notify("success", `Synced ${res.synced} video(s)`);
      await load();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Sync failed");
    } finally {
      setBusy(null);
    }
  }

  const queuePie = Object.entries(data?.queue_stats ?? {}).map(([name, value]) => ({ name: name.replaceAll("_", " "), value }));
  const noToken = !data || data.totals.videos === 0;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Publish"
        title="Analytics"
        subtitle={`Source: ${data?.source ?? "youtube_data_api"}. Metrics only appear once the API returns them — nothing here is estimated.`}
        actions={
          <button onClick={sync} disabled={busy !== null} className="btn-ghost">
            {busy === "sync" ? <Spinner /> : <Icon name="refresh" className="h-4 w-4" strokeWidth={1.9} />}
            Sync now
          </button>
        }
      />

      {noToken && (
        <Reveal>
          <div className="flex items-start gap-3 rounded-2xl border border-amber-500/20 bg-amber-500/[0.06] p-4">
            <span className="mt-0.5 text-amber-400">
              <Icon name="alert" className="h-4 w-4" />
            </span>
            <div className="text-[12px] leading-relaxed text-amber-200/85">
              <span className="font-semibold text-amber-200">No channel data yet.</span> Analytics reads the YouTube Data
              API and stays at zero until a channel is linked and videos are synced. All zeros below are real, not
              placeholders.
            </div>
          </div>
        </Reveal>
      )}

      <Stagger className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StaggerItem>
          <StatCard label="Videos" value={fmtNumber(data?.totals.videos ?? 0)} accent="violet" icon="bookmark" loading={!data} hint="Published with a real URL" />
        </StaggerItem>
        <StaggerItem>
          <StatCard label="Views" value={fmtNumber(data?.totals.views ?? 0)} accent="cyan" icon="eye" loading={!data} hint="Lifetime, from the API" />
        </StaggerItem>
        <StaggerItem>
          <StatCard label="Likes" value={fmtNumber(data?.totals.likes ?? 0)} accent="emerald" icon="check" loading={!data} hint="Lifetime, from the API" />
        </StaggerItem>
        <StaggerItem>
          <StatCard label="Comments" value={fmtNumber(data?.totals.comments ?? 0)} accent="amber" icon="list" loading={!data} hint="Lifetime, from the API" />
        </StaggerItem>
      </Stagger>

      <div className="grid gap-5 lg:grid-cols-[1.55fr_1fr]">
        <Reveal>
          <Card className="h-full">
            <SectionTitle title="Views over time" subtitle="Daily snapshots from the YouTube Data API" />
            {(data?.series ?? []).length === 0 ? (
              <Empty title="No snapshots yet" body="Analytics are recorded each time the engine syncs YouTube data." icon="chart" />
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={data?.series ?? []}>
                    <defs>
                      <linearGradient id="viewsGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.5} />
                        <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
                    <XAxis dataKey="day" tick={{ fill: "#64748b", fontSize: 10 }} stroke="rgba(255,255,255,0.08)" />
                    <YAxis tick={{ fill: "#64748b", fontSize: 10 }} stroke="rgba(255,255,255,0.08)" />
                    <Tooltip contentStyle={TOOLTIP_STYLE} />
                    <Area type="monotone" dataKey="views" stroke="#a78bfa" strokeWidth={2} fill="url(#viewsGrad)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Reveal>

        <Reveal delay={0.07}>
          <Card className="h-full">
            <SectionTitle title="Pipeline distribution" subtitle="Where your content is right now" />
            {queuePie.length === 0 ? (
              <Empty title="Queue empty" body="Nothing in the pipeline yet." icon="layers" />
            ) : (
              <div className="relative h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={queuePie} dataKey="value" nameKey="name" innerRadius={54} outerRadius={86} paddingAngle={3} stroke="none">
                      {queuePie.map((_, i) => (
                        <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={TOOLTIP_STYLE} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 grid place-items-center">
                  <div className="text-center">
                    <div className="numeric text-xl font-bold text-white">{queuePie.reduce((s, p) => s + p.value, 0)}</div>
                    <div className="text-2xs uppercase tracking-wider text-slate-500">items</div>
                  </div>
                </div>
              </div>
            )}
          </Card>
        </Reveal>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Reveal delay={0.05}>
          <Card>
            <SectionTitle title="Best performing" subtitle="Ranked by views" />
            <div className="space-y-2">
              {(data?.best ?? []).length === 0 && (
                <div className="rounded-xl border border-dashed border-white/[0.08] px-3 py-6 text-center text-[11px] text-slate-500">
                  No published videos yet.
                </div>
              )}
              {(data?.best ?? []).map((v, i) => (
                <a
                  key={v.youtube_video_id}
                  href={`https://www.youtube.com/watch?v=${v.youtube_video_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="group flex items-center gap-2.5 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2 transition-all duration-300 hover:-translate-y-0.5 hover:border-white/15"
                >
                  <span
                    className={`grid h-6 w-6 shrink-0 place-items-center rounded-md text-2xs font-bold ${
                      i === 0 ? "bg-amber-500/15 text-amber-300" : i === 1 ? "bg-slate-400/15 text-slate-300" : "bg-white/[0.06] text-slate-500"
                    }`}
                  >
                    {i + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[11.5px] text-slate-300">{v.title}</span>
                  <span className="numeric shrink-0 text-[11px] text-slate-500">{fmtNumber(v.views)}</span>
                </a>
              ))}
            </div>
          </Card>
        </Reveal>

        <Reveal delay={0.1}>
          <Card>
            <SectionTitle title="Publish hour performance" subtitle="Average views per upload hour (UTC)" />
            {(data?.per_hour ?? []).length === 0 ? (
              <div className="rounded-xl border border-dashed border-white/[0.08] px-3 py-6 text-center text-[11px] text-slate-500">
                Not enough data yet.
              </div>
            ) : (
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data?.per_hour ?? []}>
                    <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
                    <XAxis dataKey="hour" tick={{ fill: "#64748b", fontSize: 10 }} stroke="rgba(255,255,255,0.08)" />
                    <YAxis tick={{ fill: "#64748b", fontSize: 10 }} stroke="rgba(255,255,255,0.08)" />
                    <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
                    <Bar dataKey="avg_views" fill="#22d3ee" radius={[5, 5, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Reveal>
      </div>

      <Reveal delay={0.12}>
        <Card>
          <SectionTitle title="What the API actually provides" />
          <p className="text-[11.5px] leading-relaxed text-slate-400">
            AUTOSHORT AI records views, likes, comments and per-day snapshots from the YouTube Data API. Retention and
            click-through metrics require the YouTube Analytics API with channel-owner authorization; when those scopes
            are granted by Google, the same tables accept them (the source column distinguishes origins). Nothing is
            invented when a metric is unavailable.
          </p>
        </Card>
      </Reveal>
    </div>
  );
}
