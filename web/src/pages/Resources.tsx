import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Card, cx, Empty, PageHeader, Progress, Reveal, SectionTitle, Spinner, Stagger, StaggerItem, StatCard } from "../components/ui";
import { Icon } from "../components/icons";

type Gpu = {
  name: string;
  vram_total_mb: number | null;
  vram_used_mb: number | null;
  util_percent: number | null;
  temp_c: number | null;
};

type Resources = {
  cpu: { percent: number | null; cores: number | null };
  memory: { total_gb: number; used_gb: number; percent: number };
  disk: { total_gb: number; used_gb: number; free_gb: number; percent: number };
  gpu: Gpu[];
  storage: { name: string; bytes: number; mb: number; files: number }[];
  ffmpeg: string;
  data_dir: string;
  models: { name: string; size: number; family: string }[];
};

function fmtBytes(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`;
  return `${mb.toFixed(1)} MB`;
}

function tone(pct: number): string {
  if (pct >= 90) return "#fb7185";
  if (pct >= 70) return "#fbbf24";
  return "#34d399";
}

export default function ResourcesPage() {
  const { notify } = useApp();
  const [data, setData] = useState<Resources | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setData(await api.get<Resources>("/api/system/resources"));
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load resources");
    }
  }

  useEffect(() => {
    void load();
    const id = window.setInterval(load, 10000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function cleanup() {
    setBusy(true);
    try {
      const res = await api.post<{ removed: number; freed_mb: number }>("/api/system/resources/cleanup");
      notify("success", `Removed ${res.removed} temp file(s), freed ${fmtBytes(res.freed_mb)}`);
      await load();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Cleanup failed");
    } finally {
      setBusy(false);
    }
  }

  const totalStorage = (data?.storage ?? []).reduce((sum, s) => sum + s.mb, 0);
  const totalFiles = (data?.storage ?? []).reduce((sum, s) => sum + s.files, 0);
  const modelsSize = (data?.models ?? []).reduce((sum, m) => sum + m.size, 0);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Configuration"
        title="Resources"
        subtitle="Live hardware and storage telemetry, refreshed every 10 seconds."
        actions={
          <button onClick={cleanup} disabled={busy} className="btn-ghost btn-sm">
            {busy ? <Spinner /> : <Icon name="trash" className="h-3.5 w-3.5" />}
            Clean temp files
          </button>
        }
      />

      <Stagger className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StaggerItem>
          <StatCard
            label="CPU"
            value={data?.cpu.percent === null || !data ? "—" : `${Math.round(data.cpu.percent)}%`}
            accent={data?.cpu.percent && data.cpu.percent >= 70 ? "amber" : "emerald"}
            icon="chip"
            hint={`${data?.cpu.cores ?? "?"} logical cores`}
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            label="Memory"
            value={data ? `${Math.round(data.memory.percent)}%` : "—"}
            accent={data && data.memory.percent >= 85 ? "rose" : "cyan"}
            icon="layers"
            hint={data ? `${data.memory.used_gb.toFixed(1)} / ${data.memory.total_gb.toFixed(1)} GB` : "—"}
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            label="Disk"
            value={data ? `${Math.round(data.disk.percent)}%` : "—"}
            accent={data && data.disk.percent >= 90 ? "rose" : "violet"}
            icon="server"
            hint={data ? `${data.disk.free_gb.toFixed(1)} GB free of ${data.disk.total_gb.toFixed(1)} GB` : "—"}
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            label="Media files"
            value={totalFiles}
            accent="slate"
            icon="film"
            hint={fmtBytes(totalStorage)}
          />
        </StaggerItem>
      </Stagger>

      <Reveal delay={0.04}>
        <Card>
          <SectionTitle title="Load meters" subtitle="Instant readings taken from the OS" />
          <div className="grid gap-4 sm:grid-cols-3">
            <Meter title="CPU" detail={`${data?.cpu.cores ?? "?"} logical cores`} percent={data?.cpu.percent ?? 0} unknown={!data || data.cpu.percent === null} />
            <Meter
              title="Memory"
              detail={data ? `${data.memory.used_gb.toFixed(1)} / ${data.memory.total_gb.toFixed(1)} GB` : "—"}
              percent={data?.memory.percent ?? 0}
              unknown={!data}
            />
            <Meter
              title="Disk"
              detail={data ? `${data.disk.free_gb.toFixed(1)} GB free` : "—"}
              percent={data?.disk.percent ?? 0}
              unknown={!data}
            />
          </div>
        </Card>
      </Reveal>

      <div className="grid gap-5 lg:grid-cols-2">
        <Reveal delay={0.08}>
          <Card className="h-full">
            <SectionTitle title="GPU" subtitle={data?.gpu.length ? `${data.gpu.length} device(s) via nvidia-smi` : "no NVIDIA GPU detected"} />
            {data?.gpu.length ? (
              <div className="space-y-2">
                {data.gpu.map((gpu) => {
                  const pct = gpu.vram_total_mb && gpu.vram_used_mb ? (gpu.vram_used_mb / gpu.vram_total_mb) * 100 : 0;
                  return (
                    <div key={gpu.name} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                      <div className="flex items-center justify-between text-[11px]">
                        <span className="flex items-center gap-1.5 font-semibold text-slate-200">
                          <Icon name="chip" className="h-3 w-3 text-cyan-300" />
                          {gpu.name}
                        </span>
                        {gpu.temp_c !== null && <span className="numeric text-slate-500">{gpu.temp_c}°C</span>}
                      </div>
                      <div className="mt-1.5 flex items-center justify-between text-2xs text-slate-500">
                        <span>
                          VRAM {gpu.vram_used_mb?.toFixed(0) ?? "?"} / {gpu.vram_total_mb?.toFixed(0) ?? "?"} MB
                        </span>
                        <span>util {gpu.util_percent ?? 0}%</span>
                      </div>
                      <Progress value={pct} className="mt-1.5" tone="linear-gradient(90deg,#06b6d4,#22d3ee)" />
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="flex items-start gap-2.5 rounded-xl border border-dashed border-white/[0.08] p-3.5">
                <Icon name="chip" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />
                <p className="text-2xs leading-relaxed text-slate-500">
                  FFmpeg renders on CPU here. Installing an NVIDIA driver with nvidia-smi enabled will surface GPU metrics
                  automatically.
                </p>
              </div>
            )}

            <div className="mt-4 border-t border-white/[0.06] pt-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="label mb-0">Ollama models on disk</span>
                {modelsSize > 0 && <span className="numeric text-2xs text-slate-500">{(modelsSize / 1e9).toFixed(1)} GB</span>}
              </div>
              <div className="space-y-1">
                {(data?.models ?? []).map((m) => (
                  <div key={m.name} className="flex items-center justify-between rounded-lg bg-white/[0.02] px-2.5 py-1.5 text-2xs">
                    <span className="truncate font-mono text-slate-300">{m.name}</span>
                    <span className="numeric text-slate-500">{m.size ? `${(m.size / 1e9).toFixed(1)} GB` : "—"}</span>
                  </div>
                ))}
                {!data?.models.length && <div className="text-2xs text-slate-600">No models pulled yet.</div>}
              </div>
            </div>
          </Card>
        </Reveal>

        <Reveal delay={0.12}>
          <Card className="h-full">
            <SectionTitle title="Media storage" subtitle={`${totalFiles} files · ${fmtBytes(totalStorage)}`} />
            <div className="space-y-2.5">
              {(data?.storage ?? []).map((s, i) => {
                const pct = totalStorage > 0 ? (s.mb / totalStorage) * 100 : 0;
                return (
                  <motion.div
                    key={s.name}
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.35, delay: i * 0.04, ease: [0.16, 1, 0.3, 1] }}
                  >
                    <div className="flex items-center justify-between text-2xs">
                      <span className="font-semibold uppercase tracking-wider text-slate-400">{s.name}</span>
                      <span className="numeric text-slate-500">
                        {fmtBytes(s.mb)} · {s.files} file(s)
                      </span>
                    </div>
                    <Progress value={pct} className="mt-1.5" tone="linear-gradient(90deg,#8b5cf6,#a78bfa)" />
                  </motion.div>
                );
              })}
              {!data?.storage.length && (
                <Empty title="No media files yet" body="Generated audio, visuals and renders will show up here." icon="film" />
              )}
            </div>
            <div className="mt-3 flex items-center justify-between gap-2 border-t border-white/[0.06] pt-3 font-mono text-2xs text-slate-500">
              <span className="flex items-center gap-1.5">
                <Icon name="film" className="h-3 w-3" />
                ffmpeg
              </span>
              <span className="truncate text-right" title={data?.ffmpeg ?? ""}>{data?.ffmpeg ?? "—"}</span>
            </div>
          </Card>
        </Reveal>
      </div>
    </div>
  );
}

function Meter({ title, detail, percent, unknown }: { title: string; detail: string; percent: number; unknown?: boolean }) {
  const color = tone(percent);
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3.5">
      <div className="flex items-start justify-between">
        <div>
          <div className="eyebrow">{title}</div>
          <div className="mt-1 text-[12px] text-slate-300">{detail}</div>
        </div>
        <div className="numeric text-[22px] font-black leading-none" style={{ color }}>
          {unknown ? "—" : `${Math.round(percent)}%`}
        </div>
      </div>
      <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-white/[0.06]">
        <motion.div
          className={cx("h-full rounded-full")}
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(100, percent)}%` }}
          transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
          style={{ backgroundColor: color, boxShadow: `0 0 12px ${color}55` }}
        />
      </div>
    </div>
  );
}
