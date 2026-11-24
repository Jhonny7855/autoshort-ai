import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api, type Niche } from "../lib/api";
import { useApp } from "../lib/store";
import { Card, cx, Empty, PageHeader, Progress, Reveal, SectionTitle, Spinner, StatCard, Stagger, StaggerItem } from "../components/ui";
import { Icon } from "../components/icons";

type AiStatus = {
  reachable: boolean;
  base_url: string;
  models: { name: string; size: number; family: string; parameter_size: string; quantization: string }[];
  error: string | null;
  recommended_model: string;
  install_hint: string;
  usable: boolean;
};

export default function AiEngine() {
  const { notify } = useApp();
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [niches, setNiches] = useState<Niche[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [pullName, setPullName] = useState("");
  const [pullLog, setPullLog] = useState<string[]>([]);
  const [testResult, setTestResult] = useState<string | null>(null);

  async function load() {
    try {
      const [s, cfg, n] = await Promise.all([
        api.get<AiStatus>("/api/ai/status"),
        api.get<{ settings: Record<string, unknown> }>("/api/ai/settings"),
        api.get<{ niches: Niche[] }>("/api/ai/niches"),
      ]);
      setStatus(s);
      setSettings(cfg.settings);
      setNiches(n.niches);
      setPullName((prev) => prev || s.recommended_model);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load AI status");
    }
  }

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void api.get<AiStatus>("/api/ai/status").then(setStatus).catch(() => undefined), 30000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save(key: string, value: unknown) {
    setSettings((prev) => ({ ...prev, [key]: value }));
    try {
      await api.post("/api/ai/settings", { key, value });
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Save failed");
    }
  }

  async function selectModel(name: string) {
    setBusy(`model-${name}`);
    try {
      await api.post("/api/ai/models/select", { name });
      setSettings((prev) => ({ ...prev, ai_model: name }));
      notify("success", `Using ${name}`);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Model selection failed");
    } finally {
      setBusy(null);
    }
  }

  async function pull() {
    if (!pullName.trim()) return;
    setBusy("pull");
    setPullLog([]);
    try {
      const res = await fetch("/api/ai/models/pull", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: pullName.trim() }),
      });
      if (!res.body) throw new Error("No stream");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.slice(6)) as { status?: string; percent?: number | null; error?: string };
            if (data.error) setPullLog((prev) => [...prev, `error: ${data.error}`]);
            else setPullLog((prev) => [...prev.slice(-8), `${data.status}${data.percent !== null && data.percent !== undefined ? ` ${data.percent}%` : ""}`]);
          } catch {
            /* ignore */
          }
        }
      }
      notify("success", "Model pull finished");
      await load();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Pull failed");
    } finally {
      setBusy(null);
    }
  }

  async function test() {
    setBusy("test");
    setTestResult(null);
    try {
      const res = await api.post<{ ok: boolean; response?: string; error?: string }>("/api/ai/test");
      setTestResult(res.ok ? `OK · ${res.response}` : `Failed · ${res.error}`);
    } catch (err) {
      setTestResult(err instanceof Error ? err.message : "failed");
    } finally {
      setBusy(null);
    }
  }

  async function scoreNiches() {
    setBusy("score");
    try {
      const res = await api.post<{ niches: Niche[] }>("/api/ai/niches/score");
      setNiches(res.niches);
      notify("success", "Niche scores refreshed");
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Scoring failed");
    } finally {
      setBusy(null);
    }
  }

  async function activate(n: Niche) {
    try {
      await api.post("/api/ai/niches/activate", { niche_id: n.id });
      setNiches((prev) => prev.map((x) => ({ ...x, active: x.id === n.id ? 1 : 0 })));
      notify("success", `${n.name} activated`);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Activation failed");
    }
  }

  const models = status?.models ?? [];
  const activeModel = String(settings.ai_model ?? "");

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Configuration"
        title="AI engine"
        subtitle="Local models via Ollama. No API keys, no token cost."
        actions={
          <>
            <button onClick={test} disabled={busy !== null} className="btn-ghost btn-sm">
              {busy === "test" ? <Spinner /> : <Icon name="play" className="h-3.5 w-3.5" />}
              Test model
            </button>
            <button onClick={() => void load()} className="btn-ghost btn-sm">
              <Icon name="refresh" className="h-3.5 w-3.5" />
              Refresh
            </button>
          </>
        }
      />

      <Reveal>
        <div className="card-lit p-4">
          <div className="relative flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="relative grid h-10 w-10 place-items-center rounded-xl border border-white/[0.08] bg-white/[0.04]">
                <Icon name="server" className={cx("h-4 w-4", status?.reachable ? "text-emerald-300" : "text-rose-300")} />
                <span
                  className={cx(
                    "absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-ink-900",
                    status?.reachable ? "bg-emerald-400" : "bg-rose-400",
                    status?.reachable && "animate-breathe",
                  )}
                />
              </span>
              <div>
                <div className="text-sm font-semibold text-white">
                  {status?.reachable ? "Ollama reachable" : "Ollama not reachable"}
                </div>
                <div className="font-mono text-[10px] text-slate-500">{status?.base_url}</div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="chip border-white/10 bg-white/5 text-slate-400">
                <Icon name="chip" className="h-2.5 w-2.5" />
                {models.length} model{models.length === 1 ? "" : "s"}
              </span>
              {activeModel && (
                <span className="chip border-violet-500/30 bg-violet-500/10 text-violet-200">
                  <Icon name="bolt" className="h-2.5 w-2.5" />
                  {activeModel}
                </span>
              )}
            </div>
          </div>

          {testResult && (
            <motion.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="relative mt-3 rounded-lg border border-white/10 bg-black/30 p-2.5 font-mono text-[11px] text-slate-300"
            >
              {testResult}
            </motion.div>
          )}

          {!status?.reachable && (
            <div className="relative mt-3 flex items-start gap-2 rounded-lg border border-amber-500/25 bg-amber-500/[0.06] p-3 text-[11px] leading-relaxed text-amber-200/80">
              <Icon name="alert" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                Install Ollama from ollama.com, then run{" "}
                <span className="font-mono text-amber-200">ollama pull {status?.recommended_model ?? "llama3.2:3b"}</span>. Script
                generation still works without a model using the deterministic template writer.
              </span>
            </div>
          )}
        </div>
      </Reveal>

      <Stagger className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StaggerItem>
          <StatCard label="Models" value={models.length} accent="violet" icon="chip" hint="Installed on disk" />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            label="Disk used"
            value={models.length ? `${(models.reduce((s, m) => s + m.size, 0) / 1e9).toFixed(1)} GB` : "—"}
            accent="cyan"
            icon="layers"
            hint="Total weights"
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard label="Niches" value={niches.length} accent="amber" icon="bulb" hint="Scored candidates" />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            label="Engine"
            value={status?.reachable ? "Online" : "Offline"}
            accent={status?.reachable ? "emerald" : "rose"}
            icon="server"
            hint={status?.reachable ? "Ollama responding" : "Not responding"}
          />
        </StaggerItem>
      </Stagger>

      <div className="grid gap-5 lg:grid-cols-2">
        <Reveal delay={0.04}>
          <Card className="h-full">
            <SectionTitle title="Installed models" subtitle={models.length ? `${models.length} available` : "none found"} />
            <div className="space-y-2">
              {models.map((m) => {
                const selected = activeModel === m.name;
                return (
                  <button
                    key={m.name}
                    onClick={() => selectModel(m.name)}
                    disabled={busy !== null}
                    className={cx(
                      "group w-full rounded-xl border p-3 text-left transition-all duration-300 ease-smooth",
                      selected
                        ? "border-violet-500/50 bg-violet-500/[0.08]"
                        : "border-white/[0.06] bg-white/[0.02] hover:-translate-y-0.5 hover:border-white/15",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-2 text-xs font-semibold text-slate-100">
                        <Icon name="chip" className={cx("h-3 w-3", selected ? "text-violet-300" : "text-slate-500")} />
                        {m.name}
                      </span>
                      {selected ? (
                        <span className="chip border-violet-500/40 bg-violet-500/15 text-2xs text-violet-200">in use</span>
                      ) : (
                        busy === `model-${m.name}` && <Spinner />
                      )}
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-x-2.5 gap-y-1 text-2xs text-slate-500">
                      <span>{m.parameter_size || "?"}</span>
                      <span className="text-slate-700">·</span>
                      <span>{m.family}</span>
                      <span className="text-slate-700">·</span>
                      <span>{m.quantization}</span>
                      <span className="text-slate-700">·</span>
                      <span>{(m.size / 1e9).toFixed(1)} GB</span>
                    </div>
                  </button>
                );
              })}
              {models.length === 0 && (
                <Empty title="No models installed" body="Pull a small model below — 1B to 3B fits inside 8 GB of RAM." icon="chip" />
              )}
            </div>

            <div className="mt-4 border-t border-white/[0.06] pt-3">
              <span className="label">Download a model</span>
              <div className="flex gap-2">
                <input className="input" value={pullName} onChange={(e) => setPullName(e.target.value)} placeholder="llama3.2:3b" />
                <button onClick={pull} disabled={busy !== null} className="btn-primary btn-sm shrink-0">
                  {busy === "pull" ? <Spinner /> : <Icon name="download" className="h-3.5 w-3.5" />}
                  Pull
                </button>
              </div>
              <motion.div initial={false} animate={{ height: "auto" }}>
                {pullLog.length > 0 && (
                  <div className="scrollbar-thin mt-2 max-h-24 overflow-y-auto rounded-lg bg-black/40 p-2 font-mono text-[10px] text-slate-400">
                    {pullLog.map((line, i) => (
                      <motion.div key={`${i}-${line}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                        {line}
                      </motion.div>
                    ))}
                  </div>
                )}
              </motion.div>
              <p className="mt-1.5 text-2xs text-slate-500">
                Recommended for this machine: <span className="font-mono text-slate-400">{status?.recommended_model}</span>
              </p>
            </div>
          </Card>
        </Reveal>

        <Reveal delay={0.08}>
          <Card className="h-full">
            <SectionTitle title="Generation settings" subtitle="Applies to every generated script" />
            <div className="space-y-4">
              <div>
                <div className="flex items-baseline justify-between">
                  <span className="label mb-0">Temperature (creativity)</span>
                  <span className="numeric text-[11px] font-semibold text-violet-300">
                    {Number(settings.ai_temperature ?? 0.8).toFixed(2)}
                  </span>
                </div>
                <input
                  type="range"
                  min={0.1}
                  max={1.5}
                  step={0.05}
                  value={Number(settings.ai_temperature ?? 0.8)}
                  onChange={(e) => void save("ai_temperature", Number(e.target.value))}
                  className="mt-2 w-full accent-violet-500"
                />
                <Progress value={((Number(settings.ai_temperature ?? 0.8) - 0.1) / 1.4) * 100} className="mt-1.5" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <span className="label">Script length</span>
                  <select className="input" value={String(settings.script_seconds ?? 45)} onChange={(e) => void save("script_seconds", Number(e.target.value))}>
                    {[15, 30, 45, 60].map((s) => (
                      <option key={s} value={s}>{s}s</option>
                    ))}
                  </select>
                </div>
                <div>
                  <span className="label">Language</span>
                  <select className="input" value={String(settings.language ?? "en")} onChange={(e) => void save("language", e.target.value)}>
                    {[["en", "English"], ["hi", "Hindi"], ["es", "Spanish"], ["fr", "French"], ["de", "German"], ["pt", "Portuguese"]].map(([c, l]) => (
                      <option key={c} value={c}>{l}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <span className="label">Content style</span>
                <select className="input" value={String(settings.content_style ?? "energetic-explainer")} onChange={(e) => void save("content_style", e.target.value)}>
                  {["energetic-explainer", "calm-documentary", "fast-facts", "story-driven"].map((s) => (
                    <option key={s} value={s}>{s.replaceAll("-", " ")}</option>
                  ))}
                </select>
              </div>
              <div>
                <span className="label">Quality threshold</span>
                <input
                  type="number"
                  min={50}
                  max={95}
                  className="input"
                  value={Number(settings.quality_threshold ?? 75)}
                  onChange={(e) => void save("quality_threshold", Number(e.target.value))}
                />
                <p className="mt-1.5 text-2xs leading-relaxed text-slate-500">
                  Anything scoring below this is held for review instead of being published.
                </p>
              </div>
            </div>
          </Card>
        </Reveal>
      </div>

      <Reveal delay={0.12}>
        <Card>
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <SectionTitle title="Niche intelligence" subtitle="Weighted scoring across eight dimensions" />
            <button onClick={scoreNiches} disabled={busy !== null} className="btn-ghost btn-sm">
              {busy === "score" ? <Spinner /> : <Icon name="sparkles" className="h-3.5 w-3.5" />}
              Re-score with AI
            </button>
          </div>
          {niches.length === 0 ? (
            <Empty title="No niches yet" body="Niches are seeded on first run. Re-score to refresh their weighted values." icon="bulb" />
          ) : (
            <Stagger className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" step={0.03}>
              {niches.map((n) => (
                <StaggerItem key={n.id}>
                  <button
                    onClick={() => activate(n)}
                    className={cx(
                      "group h-full w-full rounded-xl border p-3 text-left transition-all duration-300 ease-smooth",
                      n.active
                        ? "border-violet-500/50 bg-violet-500/[0.08]"
                        : "border-white/[0.06] bg-white/[0.02] hover:-translate-y-0.5 hover:border-white/15",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-100">
                        {n.active && <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />}
                        {n.name}
                      </span>
                      <span
                        className={cx(
                          "chip text-2xs",
                          n.total_score >= 70
                            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                            : "border-white/10 bg-white/5 text-slate-400",
                        )}
                      >
                        {Math.round(n.total_score)}
                      </span>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-[9px] text-slate-500">
                      <span>demand {n.demand_score?.toFixed(1)}</span>
                      <span>comp {n.competition_score?.toFixed(1)}</span>
                      <span>shorts {n.shorts_fit_score?.toFixed(1)}</span>
                      <span>visual {n.visual_score?.toFixed(1)}</span>
                    </div>
                    {n.rationale && <p className="mt-2 line-clamp-2 text-2xs italic leading-relaxed text-slate-500">{n.rationale}</p>}
                  </button>
                </StaggerItem>
              ))}
            </Stagger>
          )}
        </Card>
      </Reveal>
    </div>
  );
}
