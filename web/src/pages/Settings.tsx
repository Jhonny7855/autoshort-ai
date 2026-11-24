import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api, type Channel } from "../lib/api";
import { useApp } from "../lib/store";
import { Card, cx, PageHeader, relTime, Reveal, SectionTitle, Spinner, Stagger, StaggerItem, StatCard } from "../components/ui";
import { Icon } from "../components/icons";

type GoogleInfo = { configured: boolean; linked: boolean; scope: string | null; expires_at: string | null };

type SettingsPayload = {
  settings: Record<string, unknown>;
  channel: Channel | null;
  google: GoogleInfo;
  paths: Record<string, string>;
};

type TestState = { state: "idle" | "running" | "ok" | "fail"; detail: string };

const INK = "text-slate-400";

export default function SettingsPage() {
  const { auth, notify, refreshAuth } = useApp();
  const [data, setData] = useState<SettingsPayload | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, TestState>>({
    ffmpeg: { state: "idle", detail: "" },
    tts: { state: "idle", detail: "" },
    youtube: { state: "idle", detail: "" },
  });
  const [health, setHealth] = useState<{ version: string; data_dir: string; ffmpeg: { ok: boolean; version: string } } | null>(null);

  async function load() {
    try {
      const [s, h] = await Promise.all([
        api.get<SettingsPayload>("/api/system/settings"),
        api.get<{ version: string; data_dir: string; ffmpeg: { ok: boolean; version: string } }>("/api/system/health"),
      ]);
      setData(s);
      setHealth(h);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load settings");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save(key: string, value: unknown) {
    setSaving(key);
    setData((prev) => (prev ? { ...prev, settings: { ...prev.settings, [key]: value } } : prev));
    try {
      const res = await api.post<{ settings: Record<string, unknown> }>("/api/system/settings", { key, value });
      setData((prev) => (prev ? { ...prev, settings: res.settings } : prev));
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(null);
    }
  }

  async function runTest(key: string) {
    setTests((prev) => ({ ...prev, [key]: { state: "running", detail: "" } }));
    try {
      if (key === "ffmpeg") {
        const res = await api.post<{ ok: boolean; version?: string }>("/api/system/test/ffmpeg");
        setTests((prev) => ({ ...prev, ffmpeg: { state: res.ok ? "ok" : "fail", detail: res.version ?? "" } }));
      } else if (key === "tts") {
        const res = await api.post<{ ok: boolean; provider?: string; duration?: number; error?: string }>("/api/system/test/tts");
        setTests((prev) => ({
          ...prev,
          tts: { state: res.ok ? "ok" : "fail", detail: res.ok ? `${res.provider} · ${res.duration?.toFixed(2)}s` : res.error ?? "" },
        }));
      } else {
        const res = await api.post<{ ok: boolean; channels?: number; error?: string }>("/api/system/test/youtube");
        setTests((prev) => ({
          ...prev,
          youtube: { state: res.ok ? "ok" : "fail", detail: res.ok ? `${res.channels ?? 0} channel(s)` : res.error ?? "" },
        }));
      }
    } catch (err) {
      setTests((prev) => ({ ...prev, [key]: { state: "fail", detail: err instanceof Error ? err.message : "failed" } }));
    }
  }

  async function revokeGoogle() {
    try {
      await api.post("/api/auth/google/revoke");
      notify("success", "Google access revoked locally");
      await Promise.all([load(), refreshAuth()]);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Revoke failed");
    }
  }

  const settings = data?.settings ?? {};
  const num = (key: string, fallback: number) => Number(settings[key] ?? fallback);
  const channelTitle = data?.channel?.title ?? auth?.channel?.title ?? "none";

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Configuration" title="Settings" subtitle="Connection status, render defaults and local paths.">
        {saving && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-3 flex items-center gap-2 text-2xs text-slate-500"
          >
            <Spinner className="h-3 w-3" />
            saving {saving}…
          </motion.div>
        )}
      </PageHeader>

      <Stagger className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StaggerItem>
          <StatCard
            label="Google OAuth"
            value={data?.google.configured ? "Configured" : "Not set"}
            accent={data?.google.configured ? "emerald" : "amber"}
            icon="shield"
            hint="Client id + secret"
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            label="Access token"
            value={data?.google.linked ? "Valid" : "None"}
            accent={data?.google.linked ? "emerald" : "slate"}
            icon="gear"
            hint={data?.google.linked ? relTime(data.google.expires_at) : "not linked"}
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            label="Channel"
            value={channelTitle.length > 14 ? `${channelTitle.slice(0, 13)}…` : channelTitle}
            accent={data?.channel || auth?.channel ? "violet" : "slate"}
            icon="upload"
            hint={data?.channel || auth?.channel ? "Linked" : "Not linked"}
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            label="Application"
            value={health ? `v${health.version}` : "—"}
            accent="cyan"
            icon="server"
            hint={health?.ffmpeg.ok ? "FFmpeg detected" : "FFmpeg missing"}
          />
        </StaggerItem>
      </Stagger>

      <div className="grid gap-5 lg:grid-cols-2">
        <Reveal delay={0.04}>
          <Card className="h-full">
            <SectionTitle
              title="Google / YouTube"
              subtitle={data?.google.configured ? "Credentials configured" : "Credentials missing — sign-in disabled"}
              action={
                <span
                  className={cx(
                    "inline-flex h-2 w-2 rounded-full",
                    data?.google.configured ? "bg-emerald-400" : "bg-amber-400 animate-breathe",
                  )}
                />
              }
            />
            <div className="space-y-1.5 text-[11px]">
              <Row label="Client ID" value={data?.google.configured ? "configured" : "not set"} ok={data?.google.configured} />
              <Row label="Access token" value={data?.google.linked ? `valid (${relTime(data.google.expires_at)})` : "not linked"} ok={data?.google.linked} />
              <Row label="Channel" value={channelTitle} ok={Boolean(data?.channel || auth?.channel)} />
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button onClick={() => void runTest("youtube")} disabled={tests.youtube.state === "running"} className="btn-ghost btn-sm">
                {tests.youtube.state === "running" ? <Spinner /> : <Icon name="check" className="h-3.5 w-3.5" />}
                Test connection
              </button>
              <a
                href={data?.google.configured ? "/api/auth/google/start?mode=link" : undefined}
                aria-disabled={!data?.google.configured}
                onClick={(e) => {
                  if (!data?.google.configured) {
                    e.preventDefault();
                    notify("error", "Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env, then restart the app.");
                  }
                }}
                className={cx("btn-primary btn-sm", !data?.google.configured && "pointer-events-none opacity-40")}
              >
                <Icon name="external" className="h-3.5 w-3.5" />
                Link Google account
              </a>
              {data?.google.linked && (
                <button onClick={revokeGoogle} className="btn-danger btn-sm">
                  Revoke access
                </button>
              )}
            </div>
            {tests.youtube.detail && (
              <div className={cx("mt-2 text-2xs", tests.youtube.state === "ok" ? "text-emerald-300" : "text-rose-300")}>
                {tests.youtube.detail}
              </div>
            )}
            {!data?.google.configured && (
              <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/25 bg-amber-500/[0.06] p-3 text-2xs leading-relaxed text-amber-200/80">
                <Icon name="alert" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  Create an OAuth client in Google Cloud Console, enable the YouTube Data API v3, then add
                  <span className="font-mono"> GOOGLE_CLIENT_ID</span> and <span className="font-mono">GOOGLE_CLIENT_SECRET</span> to
                  <span className="font-mono"> .env</span>. Redirect URI:{" "}
                  <span className="font-mono">http://127.0.0.1:8787/api/auth/google/callback</span>
                </span>
              </div>
            )}
          </Card>
        </Reveal>

        <Reveal delay={0.08}>
          <Card className="h-full">
            <SectionTitle title="Diagnostics" subtitle="Real checks against installed tooling" />
            <div className="space-y-2">
              <DiagRow
                label="FFmpeg"
                status={tests.ffmpeg.state}
                detail={tests.ffmpeg.detail || (health?.ffmpeg.ok ? health.ffmpeg.version.split("\n")[0] : "missing")}
                onRun={() => void runTest("ffmpeg")}
              />
              <DiagRow label="Text to speech" status={tests.tts.state} detail={tests.tts.detail || "not tested"} onRun={() => void runTest("tts")} />
              <DiagRow label="Application" status={health ? "ok" : "idle"} detail={health ? `v${health.version}` : "unknown"} />
            </div>
            <div className="mt-3 flex items-center justify-between gap-2 border-t border-white/[0.06] pt-3 text-2xs text-slate-500">
              <span className="flex items-center gap-1.5">
                <Icon name="server" className="h-3 w-3" />
                Data directory
              </span>
              <span className="truncate font-mono text-slate-400" title={data?.paths.data ?? health?.data_dir ?? ""}>
                {data?.paths.data ?? health?.data_dir ?? "—"}
              </span>
            </div>
          </Card>
        </Reveal>
      </div>

      <Reveal delay={0.1}>
        <Card>
          <SectionTitle title="Production defaults" subtitle="Applied to every new video unless overridden" />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <span className="label">Render preset</span>
              <select className="input" value={String(settings.render_preset ?? "balanced")} onChange={(e) => void save("render_preset", e.target.value)}>
                {["lowend", "fast", "balanced", "high"].map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>
            <div>
              <span className="label">Subtitle style</span>
              <select className="input" value={String(settings.subtitle_style ?? "modern-bold")} onChange={(e) => void save("subtitle_style", e.target.value)}>
                {["modern-bold", "clean-white", "neon-pop", "minimal", "karaoke-yellow", "outline-block", "bold-bottom"].map((s) => (
                  <option key={s} value={s}>{s.replaceAll("-", " ")}</option>
                ))}
              </select>
            </div>
            <div>
              <span className="label">Subtitle size</span>
              <input
                type="number"
                min={40}
                max={140}
                className="input"
                defaultValue={num("subtitle_size", 86)}
                onBlur={(e) => void save("subtitle_size", Number(e.target.value))}
              />
            </div>
            <div>
              <span className="label">Music bed</span>
              <button
                onClick={() => void save("music_enabled", !settings.music_enabled)}
                className={cx(
                  "flex w-full items-center justify-between rounded-xl border px-3.5 py-2.5 text-sm font-semibold transition-all duration-300 ease-smooth",
                  settings.music_enabled
                    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                    : "border-white/10 text-slate-400 hover:border-white/20",
                )}
              >
                {settings.music_enabled ? "Enabled" : "Disabled"}
                <span className={cx("h-1.5 w-1.5 rounded-full", settings.music_enabled ? "bg-emerald-400" : "bg-slate-600")} />
              </button>
            </div>
            <div>
              <div className="flex items-baseline justify-between">
                <span className="label mb-0">Music volume</span>
                <span className="numeric text-[11px] font-semibold text-violet-300">{num("music_volume", 0.18).toFixed(2)}</span>
              </div>
              <input
                type="range"
                min={0}
                max={0.5}
                step={0.02}
                value={num("music_volume", 0.18)}
                onChange={(e) => void save("music_volume", Number(e.target.value))}
                className="mt-2 w-full accent-violet-500"
              />
            </div>
            <div>
              <span className="label">Quality threshold</span>
              <input
                type="number"
                min={50}
                max={95}
                className="input"
                defaultValue={num("quality_threshold", 75)}
                onBlur={(e) => void save("quality_threshold", Number(e.target.value))}
              />
            </div>
            <div>
              <span className="label">Auto improve</span>
              <button
                onClick={() => void save("auto_improve", !settings.auto_improve)}
                className={cx(
                  "flex w-full items-center justify-between rounded-xl border px-3.5 py-2.5 text-sm font-semibold transition-all duration-300 ease-smooth",
                  settings.auto_improve
                    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                    : "border-white/10 text-slate-400 hover:border-white/20",
                )}
              >
                {settings.auto_improve ? "On" : "Off"}
                <span className={cx("h-1.5 w-1.5 rounded-full", settings.auto_improve ? "bg-emerald-400" : "bg-slate-600")} />
              </button>
            </div>
          </div>
        </Card>
      </Reveal>

      <Reveal delay={0.14}>
        <Card>
          <SectionTitle title="Local storage paths" subtitle="Everything stays on this machine" />
          <div className="grid gap-1.5 text-2xs sm:grid-cols-2">
            {Object.entries(data?.paths ?? {}).map(([name, path]) => (
              <div key={name} className="flex items-center justify-between gap-2 rounded-lg bg-white/[0.02] px-2.5 py-1.5 transition-colors hover:bg-white/[0.04]">
                <span className={cx("shrink-0 font-semibold uppercase tracking-wider", INK)}>{name}</span>
                <span className="truncate font-mono text-slate-500" title={path}>{path}</span>
              </div>
            ))}
          </div>
        </Card>
      </Reveal>
    </div>
  );
}

function Row({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg bg-white/[0.02] px-2.5 py-1.5">
      <span className={cx("font-semibold uppercase tracking-wider", INK)}>{label}</span>
      <span className={cx("flex items-center gap-1.5", ok ? "text-emerald-300" : "text-slate-500")}>
        <span className={cx("h-1.5 w-1.5 rounded-full", ok ? "bg-emerald-400" : "bg-slate-600")} />
        {value}
      </span>
    </div>
  );
}

function DiagRow({
  label,
  status,
  detail,
  onRun,
}: {
  label: string;
  status: "idle" | "running" | "ok" | "fail";
  detail: string;
  onRun?: () => void;
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-white/[0.02] px-2.5 py-2">
      <span
        className={cx(
          "h-1.5 w-1.5 shrink-0 rounded-full",
          status === "ok" && "bg-emerald-400",
          status === "fail" && "bg-rose-400",
          status === "running" && "bg-amber-400 animate-breathe",
          status === "idle" && "bg-slate-600",
        )}
      />
      <div className="min-w-0 flex-1">
        <div className="text-[11px] font-semibold text-slate-200">{label}</div>
        <div className="truncate text-2xs text-slate-500" title={detail}>{detail || "—"}</div>
      </div>
      {onRun && (
        <button onClick={onRun} disabled={status === "running"} className="btn-ghost btn-sm">
          {status === "running" ? <Spinner /> : "Test"}
        </button>
      )}
    </div>
  );
}
