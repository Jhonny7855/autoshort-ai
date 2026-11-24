import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { api, type Idea, type Project, type Scene, type Script } from "../lib/api";
import { useApp } from "../lib/store";
import { Card, cx, Empty, PageHeader, Reveal, Spinner, StatusChip } from "../components/ui";
import { Icon } from "../components/icons";

type Detail = {
  idea: Idea;
  sources: { id: number; title: string; url: string; source_type: string; snippet: string }[];
  script: Script | null;
  project: Project | null;
};

export default function ScriptStudio() {
  const { notify } = useApp();
  const [params, setParams] = useSearchParams();
  const ideaId = params.get("idea");
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [form, setForm] = useState<Partial<Script>>({});
  const [seconds, setSeconds] = useState(45);

  const loadIdeas = useCallback(async () => {
    try {
      const data = await api.get<{ ideas: Idea[] }>("/api/content/ideas?limit=100");
      setIdeas(data.ideas);
      if (!ideaId && data.ideas.length > 0) setParams({ idea: String(data.ideas[0].id) }, { replace: true });
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load ideas");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadDetail = useCallback(
    async (id: number) => {
      try {
        const data = await api.get<Detail>(`/api/content/ideas/${id}`);
        setDetail(data);
        if (data.script) {
          setForm(data.script);
          setSeconds(data.script.target_seconds);
        } else {
          setForm({});
        }
      } catch (err) {
        notify("error", err instanceof Error ? err.message : "Failed to load idea");
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  useEffect(() => {
    void loadIdeas();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (ideaId) void loadDetail(Number(ideaId));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ideaId]);

  async function generate() {
    if (!ideaId) return;
    setBusy("gen");
    try {
      const res = await api.post<{ script: Script }>(`/api/content/ideas/${ideaId}/script?seconds=${seconds}`);
      setForm(res.script);
      await loadDetail(Number(ideaId));
      notify("success", "Script generated");
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Generation failed");
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    if (!detail?.script) return;
    setBusy("save");
    try {
      const res = await api.patch<{ script: Script }>(`/api/content/scripts/${detail.script.id}`, {
        hook: form.hook,
        body: form.body,
        cta: form.cta,
        title: form.title,
        description: form.description,
        hashtags: form.hashtags,
        pinned_comment: form.pinned_comment,
        voice_direction: form.voice_direction,
        target_seconds: Number(form.target_seconds) || 45,
      });
      setDetail({ ...detail, script: res.script });
      setForm(res.script);
      notify("success", "Script saved");
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(null);
    }
  }

  async function regenerateScenes() {
    if (!detail?.script) return;
    setBusy("scenes");
    try {
      const res = await api.post<{ scenes: Scene[] }>(`/api/content/scripts/${detail.script.id}/scenes/regenerate`);
      setDetail({ ...detail, script: { ...detail.script, scenes: res.scenes } });
      notify("success", `${res.scenes.length} scenes rebuilt from the script`);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Scene rebuild failed");
    } finally {
      setBusy(null);
    }
  }

  async function patchScene(scene: Scene, patch: Partial<Scene>) {
    setBusy(`scene-${scene.id}`);
    try {
      await api.patch(`/api/content/scenes/${scene.id}`, patch);
      if (detail?.script?.scenes) {
        setDetail({
          ...detail,
          script: { ...detail.script, scenes: detail.script.scenes.map((s) => (s.id === scene.id ? { ...s, ...patch } : s)) },
        });
      }
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Scene update failed");
    } finally {
      setBusy(null);
    }
  }

  async function approve() {
    if (!detail?.script) return;
    setBusy("approve");
    try {
      await api.patch(`/api/content/scripts/${detail.script.id}`, { approved: 1 });
      setDetail({ ...detail, script: { ...detail.script, approved: 1 } });
      notify("success", "Script approved");
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Approval failed");
    } finally {
      setBusy(null);
    }
  }

  const wordCount = (form.body ?? "").split(/\s+/).filter(Boolean).length;
  const estSeconds = Math.round(wordCount / 2.6);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Studio"
        title="Script studio"
        subtitle="Hook, body, metadata and scene breakdown — all editable before rendering."
        actions={
          <select className="input w-full sm:w-72" value={ideaId ?? ""} onChange={(e) => setParams({ idea: e.target.value })}>
            <option value="">Select an idea</option>
            {ideas.map((i) => (
              <option key={i.id} value={i.id}>
                {i.topic.slice(0, 60)}
              </option>
            ))}
          </select>
        }
      />

      {!detail ? (
        <Empty title="Select an idea" body="Pick an idea above to research it and generate a script." icon="doc" />
      ) : (
        <div className="grid gap-5 xl:grid-cols-[1.55fr_1fr]">
          <div className="space-y-5">
            <Reveal>
              <Card>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <h2 className="truncate text-[13.5px] font-semibold text-white">{detail.idea.topic}</h2>
                    <StatusChip status={detail.idea.status} />
                  </div>
                  <div className="flex gap-1.5">
                    <button onClick={generate} disabled={busy !== null} className="btn-primary btn-sm">
                      {busy === "gen" ? <Spinner /> : <Icon name="sparkles" className="h-3 w-3" />}
                      {detail.script ? "Regenerate" : "Generate script"}
                    </button>
                    {detail.script && (
                      <button onClick={save} disabled={busy !== null} className="btn-ghost btn-sm">
                        {busy === "save" ? <Spinner /> : <Icon name="check" className="h-3 w-3" strokeWidth={2.4} />}
                        Save
                      </button>
                    )}
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="text-2xs font-bold uppercase tracking-wider text-slate-600">Length</span>
                  {[15, 30, 45, 60].map((s) => (
                    <motion.button
                      key={s}
                      whileTap={{ scale: 0.94 }}
                      onClick={() => setSeconds(s)}
                      className={cx(
                        "rounded-md border px-2.5 py-1 text-[11px] font-semibold transition-all duration-200",
                        seconds === s ? "border-cyan-500/40 bg-cyan-500/10 text-cyan-200" : "border-white/10 text-slate-500 hover:border-white/20",
                      )}
                    >
                      {s}s
                    </motion.button>
                  ))}
                  <span className="ml-auto text-2xs text-slate-500">
                    {wordCount} words · ~{estSeconds}s spoken
                  </span>
                </div>

                {detail.script ? (
                  <div className="mt-4 space-y-3.5">
                    <Field label="Hook (first 1–3 seconds)">
                      <textarea className="input min-h-[64px]" value={form.hook ?? ""} onChange={(e) => setForm({ ...form, hook: e.target.value })} />
                    </Field>
                    <Field label="Script body">
                      <textarea
                        className="input min-h-[190px] font-mono text-[12.5px] leading-relaxed"
                        value={form.body ?? ""}
                        onChange={(e) => setForm({ ...form, body: e.target.value })}
                      />
                    </Field>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Field label="CTA">
                        <input className="input" value={form.cta ?? ""} onChange={(e) => setForm({ ...form, cta: e.target.value })} />
                      </Field>
                      <Field label="Title">
                        <input className="input" value={form.title ?? ""} onChange={(e) => setForm({ ...form, title: e.target.value })} />
                      </Field>
                    </div>
                    <Field label="Description">
                      <textarea
                        className="input min-h-[90px]"
                        value={form.description ?? ""}
                        onChange={(e) => setForm({ ...form, description: e.target.value })}
                      />
                    </Field>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Field label="Hashtags (comma separated)">
                        <input
                          className="input"
                          value={(form.hashtags ?? []).join(", ")}
                          onChange={(e) =>
                            setForm({ ...form, hashtags: e.target.value.split(",").map((t) => t.trim()).filter(Boolean) })
                          }
                        />
                      </Field>
                      <Field label="Pinned comment">
                        <input className="input" value={form.pinned_comment ?? ""} onChange={(e) => setForm({ ...form, pinned_comment: e.target.value })} />
                      </Field>
                    </div>
                    <Field label="Voice direction">
                      <input className="input" value={form.voice_direction ?? ""} onChange={(e) => setForm({ ...form, voice_direction: e.target.value })} />
                    </Field>

                    {form.alt_hooks && form.alt_hooks.length > 0 && (
                      <div>
                        <span className="label">Alternative hooks</span>
                        <div className="space-y-1.5">
                          {form.alt_hooks.map((h, i) => (
                            <button
                              key={i}
                              onClick={() => setForm({ ...form, hook: h })}
                              className="group flex w-full items-center gap-2 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2 text-left text-[11px] text-slate-300 transition-all duration-200 hover:border-violet-500/40 hover:bg-violet-500/[0.06] hover:text-white"
                            >
                              <Icon name="arrowRight" className="h-3 w-3 shrink-0 text-slate-600 transition group-hover:text-violet-300" />
                              <span className="flex-1">{h}</span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="flex items-center justify-between border-t border-white/[0.06] pt-3">
                      <span className={cx("flex items-center gap-1.5 text-[11px]", detail.script.approved ? "text-emerald-300" : "text-amber-300")}>
                        <Icon name={detail.script.approved ? "check" : "clock"} className="h-3 w-3" strokeWidth={2.4} />
                        {detail.script.approved ? "Approved for production" : "Not approved yet"}
                      </span>
                      <button onClick={approve} disabled={busy !== null || detail.script.approved === 1} className="btn-ghost btn-sm">
                        {busy === "approve" ? <Spinner /> : "Approve script"}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="mt-4 rounded-xl border border-dashed border-white/[0.08] px-4 py-10 text-center text-[12px] text-slate-500">
                    No script yet for this idea.
                  </div>
                )}
              </Card>
            </Reveal>

            {detail.script && (
              <Reveal delay={0.06}>
                <Card>
                  <div className="flex items-center justify-between">
                    <div>
                      <h2 className="text-[13.5px] font-semibold text-white">Scenes</h2>
                      <p className="mt-0.5 text-[11px] text-slate-500">{(detail.script.scenes ?? []).length} scenes · edits save on change</p>
                    </div>
                    <button onClick={regenerateScenes} disabled={busy !== null} className="btn-ghost btn-sm">
                      {busy === "scenes" ? <Spinner /> : <Icon name="refresh" className="h-3 w-3" />}
                      Rebuild
                    </button>
                  </div>
                  <div className="mt-3 space-y-2">
                    {(detail.script.scenes ?? []).map((scene, i) => (
                      <motion.div
                        key={scene.id}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: Math.min(i * 0.04, 0.2) }}
                        className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3"
                      >
                        <div className="flex items-center justify-between text-2xs font-bold uppercase tracking-wider text-slate-600">
                          <span>Scene {scene.scene_no}</span>
                          <span className="numeric normal-case">
                            {scene.duration.toFixed(1)}s · {scene.motion.replaceAll("_", " ")}
                          </span>
                        </div>
                        <textarea
                          className="input mt-2 min-h-[56px] text-[12px]"
                          value={scene.narration}
                          onChange={(e) => patchScene(scene, { narration: e.target.value })}
                        />
                        <input
                          className="input mt-1.5 text-[11px]"
                          value={scene.visual_prompt}
                          onChange={(e) => patchScene(scene, { visual_prompt: e.target.value })}
                          placeholder="Visual prompt"
                        />
                        <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                          <select className="input text-[11px]" value={scene.motion} onChange={(e) => patchScene(scene, { motion: e.target.value })}>
                            {["zoom_in", "zoom_out", "pan_left", "pan_right", "ken_burns"].map((m) => (
                              <option key={m} value={m}>
                                {m.replaceAll("_", " ")}
                              </option>
                            ))}
                          </select>
                          <select className="input text-[11px]" value={scene.transition} onChange={(e) => patchScene(scene, { transition: e.target.value })}>
                            {["fade", "slide", "whip", "none"].map((t) => (
                              <option key={t} value={t}>
                                {t}
                              </option>
                            ))}
                          </select>
                        </div>
                      </motion.div>
                    ))}
                    {!(detail.script.scenes ?? []).length && <div className="text-xs text-slate-500">No scenes. Generate a script first.</div>}
                  </div>
                </Card>
              </Reveal>
            )}
          </div>

          <div className="space-y-5">
            <Reveal delay={0.04}>
              <Card>
                <h2 className="text-[13.5px] font-semibold text-white">Research sources</h2>
                <p className="mt-0.5 text-[11px] text-slate-500">Grounding for the script. Verify facts before publishing.</p>
                <div className="mt-3 space-y-2">
                  {detail.sources.length === 0 && (
                    <div className="rounded-xl border border-dashed border-white/[0.08] px-3 py-6 text-center text-[11px] text-slate-500">
                      No sources collected yet.
                    </div>
                  )}
                  {detail.sources.map((src) => (
                    <a
                      key={src.id}
                      href={src.url}
                      target="_blank"
                      rel="noreferrer"
                      className="group block rounded-xl border border-white/[0.05] bg-white/[0.02] p-2.5 transition-all duration-300 hover:-translate-y-0.5 hover:border-white/15"
                    >
                      <span className="chip border-cyan-500/25 bg-cyan-500/10 text-[9px] text-cyan-300">{src.source_type}</span>
                      <div className="mt-1.5 line-clamp-2 text-[11px] font-semibold text-slate-200">{src.title}</div>
                      <div className="mt-1 line-clamp-3 text-[10px] leading-relaxed text-slate-500">{src.snippet}</div>
                    </a>
                  ))}
                </div>
              </Card>
            </Reveal>

            <Reveal delay={0.1}>
              <Card>
                <h2 className="text-[13.5px] font-semibold text-white">Compliance check</h2>
                <ul className="mt-2 space-y-2 text-[11px] leading-relaxed text-slate-400">
                  <li className="flex gap-2">
                    <Icon name="shield" className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400/80" />
                    <span>
                      Originality fingerprint:{" "}
                      <span className="font-mono text-[10px] text-slate-300">
                        {detail.idea.topic.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40)}
                      </span>
                    </span>
                  </li>
                  <li className="flex gap-2">
                    <Icon name="check" className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400/80" />
                    Duplicate topics are blocked at creation time.
                  </li>
                  <li className="flex gap-2">
                    <Icon name="check" className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400/80" />
                    No invented statistics: prompts keep the model within the sources above.
                  </li>
                  <li className="flex gap-2">
                    <Icon name="alert" className="mt-0.5 h-3 w-3 shrink-0 text-amber-400/80" />
                    Sensitive topics (health, finance, politics, news) should stay in approval mode.
                  </li>
                </ul>
              </Card>
            </Reveal>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="label">{label}</span>
      {children}
    </div>
  );
}
