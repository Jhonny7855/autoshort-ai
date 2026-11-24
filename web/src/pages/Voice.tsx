import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Card, cx, PageHeader, Progress, Reveal, SectionTitle, Spinner, StatCard, Stagger, StaggerItem } from "../components/ui";
import { Icon } from "../components/icons";

type Voice = { id: string; label: string };

type Capabilities = {
  piper: { available: boolean; detail: string };
  sapi: { available: boolean; voices: Voice[] };
  edge: { available: boolean; voices: Voice[]; needs_internet: boolean };
  chain: string[];
  offline_capable: boolean;
};

type VoicePayload = {
  providers: Capabilities;
  voices: { edge: Voice[]; sapi: Voice[] };
  default: string | null;
};

type AiSettings = { settings: Record<string, unknown> };

const PROVIDER_LABEL: Record<string, string> = {
  piper: "Piper (offline neural)",
  sapi: "Windows SAPI (offline)",
  edge: "Edge TTS (free, internet)",
};

const PROVIDER_META: Record<string, { icon: "chip" | "server" | "mic"; fallback: string }> = {
  piper: { icon: "chip", fallback: "install piper + set PIPER_VOICE_MODEL" },
  sapi: { icon: "mic", fallback: "not detected on this OS" },
  edge: { icon: "server", fallback: "pip install edge-tts" },
};

export default function VoicePage() {
  const { notify } = useApp();
  const [payload, setPayload] = useState<VoicePayload | null>(null);
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [provider, setProvider] = useState("auto");
  const [voice, setVoice] = useState("");
  const [text, setText] = useState("This is how your narration will sound.");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{ url: string; provider: string; duration: number } | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  async function load() {
    try {
      const [v, s] = await Promise.all([
        api.get<VoicePayload>("/api/content/voices"),
        api.get<AiSettings>("/api/ai/settings"),
      ]);
      setPayload(v);
      setSettings(s.settings);
      setProvider(String(s.settings.tts_provider ?? "auto"));
      setVoice(String(s.settings.tts_voice ?? ""));
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load voices");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function persist(key: string, value: unknown) {
    setSettings((prev) => ({ ...prev, [key]: value }));
    try {
      await api.post("/api/ai/settings", { key, value });
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Save failed");
    }
  }

  const edgeVoices = payload?.voices.edge ?? [];
  const sapiVoices = payload?.voices.sapi ?? [];
  const voiceList = provider === "sapi" ? sapiVoices : provider === "edge" ? edgeVoices : [...edgeVoices, ...sapiVoices];

  async function runPreview() {
    setBusy(true);
    setPreview(null);
    try {
      const params = new URLSearchParams({ text: text.slice(0, 200) });
      if (voice) params.set("voice", voice);
      if (provider) params.set("provider", provider);
      const res = await api.post<{ url: string; provider: string; duration: number }>(
        `/api/content/voices/preview?${params.toString()}`,
      );
      setPreview(res);
      notify("success", `Rendered with ${res.provider}`);
      window.setTimeout(() => audioRef.current?.play().catch(() => undefined), 120);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Preview failed");
    } finally {
      setBusy(false);
    }
  }

  const rate = Number(settings.tts_rate ?? 0);
  const availableCount = (["piper", "sapi", "edge"] as const).filter((key) => payload?.providers[key]?.available).length;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Configuration"
        title="Voice"
        subtitle="Local narration engines only. No paid speech API is ever contacted."
        actions={
          <span className={cx("chip", payload?.providers.offline_capable ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" : "border-amber-500/30 bg-amber-500/10 text-amber-300")}>
            <Icon name="shield" className="h-2.5 w-2.5" />
            {payload?.providers.offline_capable ? "offline capable" : "needs internet"}
          </span>
        }
      />

      <Stagger className="grid gap-3 sm:grid-cols-3">
        <StaggerItem>
          <StatCard label="Engines available" value={availableCount} accent={availableCount ? "emerald" : "amber"} icon="mic" hint="Detected on this machine" />
        </StaggerItem>
        <StaggerItem>
          <StatCard label="Voices" value={voiceList.length} accent="violet" icon="list" hint={provider === "auto" ? "All providers" : PROVIDER_LABEL[provider]} />
        </StaggerItem>
        <StaggerItem>
          <StatCard label="Speaking rate" value={`${rate > 0 ? "+" : ""}${rate}%`} accent="cyan" icon="clock" hint="Applied to every scene" />
        </StaggerItem>
      </Stagger>

      <Reveal>
        <Card>
          <SectionTitle title="Available engines" subtitle={payload ? `chain: ${payload.providers.chain.join(" → ") || "none"}` : "detecting"} />
          <div className="grid gap-2 sm:grid-cols-3">
            {(["piper", "sapi", "edge"] as const).map((key, i) => {
              const caps = payload?.providers[key] as
                | { available: boolean; detail?: string; voices?: Voice[]; needs_internet?: boolean }
                | undefined;
              const meta = PROVIDER_META[key];
              return (
                <motion.div
                  key={key}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4, delay: i * 0.06, ease: [0.16, 1, 0.3, 1] }}
                  className={cx(
                    "relative overflow-hidden rounded-xl border p-3 transition-colors duration-300",
                    caps?.available
                      ? "border-emerald-500/25 bg-emerald-500/[0.06]"
                      : "border-white/[0.06] bg-white/[0.02]",
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="flex items-center gap-2">
                      <span className={cx("grid h-7 w-7 place-items-center rounded-lg border", caps?.available ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300" : "border-white/[0.06] bg-white/[0.03] text-slate-500")}>
                        <Icon name={meta.icon} className="h-3.5 w-3.5" />
                      </span>
                      <span className="text-xs font-semibold text-slate-100">{PROVIDER_LABEL[key]}</span>
                    </span>
                    <span
                      className={cx(
                        "mt-1 h-2 w-2 shrink-0 rounded-full",
                        caps?.available ? "bg-emerald-400 animate-breathe" : "bg-slate-600",
                      )}
                    />
                  </div>
                  <div className="mt-2 text-2xs leading-relaxed text-slate-500">
                    {caps?.available
                      ? key === "piper"
                        ? caps.detail || "model configured"
                        : `${caps.voices?.length ?? 0} voice(s)`
                      : meta.fallback}
                  </div>
                </motion.div>
              );
            })}
          </div>
          <div className="mt-3 flex items-center gap-1.5 text-[11px] text-slate-500">
            <Icon name="refresh" className="h-3 w-3" />
            The chain falls back automatically when a provider fails — nothing is replaced with silence.
          </div>
        </Card>
      </Reveal>

      <div className="grid gap-5 lg:grid-cols-2">
        <Reveal delay={0.04}>
          <Card className="h-full">
            <SectionTitle title="Narration defaults" subtitle="Used by every generated scene" />
            <div className="space-y-4">
              <div>
                <span className="label">Provider</span>
                <select
                  className="input"
                  value={provider}
                  onChange={(e) => {
                    setProvider(e.target.value);
                    void persist("tts_provider", e.target.value);
                  }}
                >
                  <option value="auto">Auto (recommended)</option>
                  <option value="edge">Edge TTS</option>
                  <option value="sapi">Windows SAPI</option>
                  <option value="piper">Piper</option>
                </select>
              </div>
              <div>
                <span className="label">Voice</span>
                <select
                  className="input"
                  value={voice}
                  onChange={(e) => {
                    setVoice(e.target.value);
                    void persist("tts_voice", e.target.value);
                  }}
                >
                  <option value="">Default for provider</option>
                  {voiceList.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <div className="flex items-baseline justify-between">
                  <span className="label mb-0">Speaking rate</span>
                  <span className="numeric text-[11px] font-semibold text-violet-300">
                    {rate > 0 ? "+" : ""}
                    {rate}%
                  </span>
                </div>
                <input
                  type="range"
                  min={-30}
                  max={40}
                  step={5}
                  value={rate}
                  onChange={(e) => {
                    const value = Number(e.target.value);
                    setSettings((prev) => ({ ...prev, tts_rate: value }));
                  }}
                  onPointerUp={() => void persist("tts_rate", Number(settings.tts_rate ?? 0))}
                  className="mt-2 w-full accent-violet-500"
                />
                <Progress value={((rate + 30) / 70) * 100} className="mt-1.5" />
              </div>
            </div>
          </Card>
        </Reveal>

        <Reveal delay={0.08}>
          <Card className="h-full">
            <SectionTitle title="Preview" subtitle="Renders a real wav file through the selected engine" />
            <textarea
              className="input min-h-[92px] resize-y"
              value={text}
              maxLength={200}
              onChange={(e) => setText(e.target.value)}
              placeholder="Type a sample line"
            />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button onClick={runPreview} disabled={busy || !text.trim()} className="btn-primary btn-sm">
                {busy ? <Spinner /> : <Icon name="play" className="h-3.5 w-3.5" />}
                Generate preview
              </button>
              <span className="numeric text-2xs text-slate-500">{text.length}/200 characters</span>
            </div>
            <AnimatePresence initial={false}>
              {preview && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="overflow-hidden"
                >
                  <div className="mt-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                    <div className="mb-2 flex items-center justify-between text-2xs text-slate-500">
                      <span className="flex items-center gap-1.5 font-mono">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                        {preview.provider}
                      </span>
                      <span>{preview.duration.toFixed(2)}s</span>
                    </div>
                    <audio ref={audioRef} controls src={preview.url} className="w-full" />
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </Card>
        </Reveal>
      </div>

      <Reveal delay={0.12}>
        <Card>
          <SectionTitle title="How the fallback works" subtitle="Deterministic order, always local-first" />
          <ol className="grid gap-2 sm:grid-cols-2">
            {[
              "Piper is tried when a local voice model is configured (fully offline).",
              "Windows SAPI is used next — always available offline on Windows.",
              "Edge TTS is the last resort; it needs internet but no key or account.",
              "Failures are logged and never replaced with silence or fake audio.",
            ].map((line, i) => (
              <li key={line} className="flex items-start gap-2.5 rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
                <span className="numeric grid h-5 w-5 shrink-0 place-items-center rounded-md bg-violet-500/15 text-2xs font-bold text-violet-300">
                  {i + 1}
                </span>
                <span className="text-[11.5px] leading-relaxed text-slate-400">{line}</span>
              </li>
            ))}
          </ol>
        </Card>
      </Reveal>
    </div>
  );
}
