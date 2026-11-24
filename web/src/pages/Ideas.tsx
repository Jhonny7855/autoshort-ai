import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { api, type Idea } from "../lib/api";
import { useApp } from "../lib/store";
import { Card, Empty, PageHeader, relTime, Reveal, SectionTitle, Spinner, StatusChip } from "../components/ui";
import { Icon } from "../components/icons";

export default function Ideas() {
  const { notify } = useApp();
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [topic, setTopic] = useState("");
  const [angle, setAngle] = useState("");
  const [filter, setFilter] = useState("");

  async function load() {
    try {
      const data = await api.get<{ ideas: Idea[] }>("/api/content/ideas?limit=100");
      setIdeas(data.ideas);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load ideas");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function generate() {
    setBusy("generate");
    try {
      const res = await api.post<{ idea: Idea }>("/api/content/ideas", { auto: true });
      setIdeas((prev) => [res.idea, ...prev.filter((i) => i.id !== res.idea.id)]);
      notify("success", `New idea: ${res.idea.topic}`);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Idea generation failed");
    } finally {
      setBusy(null);
    }
  }

  async function addManual() {
    if (!topic.trim()) return;
    setBusy("manual");
    try {
      const res = await api.post<{ idea: Idea }>("/api/content/ideas", { topic: topic.trim(), angle: angle.trim() || null });
      setIdeas((prev) => [res.idea, ...prev.filter((i) => i.id !== res.idea.id)]);
      setTopic("");
      setAngle("");
      notify("success", "Idea added");
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Could not add idea");
    } finally {
      setBusy(null);
    }
  }

  async function research(idea: Idea) {
    setBusy(`r-${idea.id}`);
    try {
      await api.post(`/api/content/ideas/${idea.id}/research`);
      notify("success", "Research sources collected");
      await load();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Research failed");
    } finally {
      setBusy(null);
    }
  }

  async function writeScript(idea: Idea) {
    setBusy(`s-${idea.id}`);
    try {
      await api.post(`/api/content/ideas/${idea.id}/script`);
      notify("success", "Script generated");
      await load();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Script generation failed");
    } finally {
      setBusy(null);
    }
  }

  async function enqueue(idea: Idea) {
    setBusy(`q-${idea.id}`);
    try {
      await api.post("/api/video/ideas/" + idea.id + "/produce", { force: false });
      notify("success", "Queued and produced");
      await load();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Production failed");
    } finally {
      setBusy(null);
    }
  }

  async function remove(idea: Idea) {
    setBusy(`d-${idea.id}`);
    try {
      await api.del(`/api/content/ideas/${idea.id}`);
      setIdeas((prev) => prev.filter((i) => i.id !== idea.id));
      notify("info", "Idea deleted");
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusy(null);
    }
  }

  const filtered = useMemo(
    () =>
      ideas.filter(
        (i) =>
          !filter ||
          i.topic.toLowerCase().includes(filter.toLowerCase()) ||
          (i.angle ?? "").toLowerCase().includes(filter.toLowerCase()),
      ),
    [ideas, filter],
  );

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Studio"
        title="Content ideas"
        subtitle="Discovery uses your active niche and avoids duplicate fingerprints."
        actions={
          <>
            <div className="relative">
              <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
              <input
                className="input w-56 py-2 pl-9 text-xs"
                placeholder="Filter ideas"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            </div>
            <button onClick={generate} disabled={busy !== null} className="btn-primary">
              {busy === "generate" ? <Spinner /> : <Icon name="sparkles" className="h-4 w-4" />}
              Generate with AI
            </button>
          </>
        }
      />

      <Reveal>
        <Card>
          <SectionTitle title="Add a specific idea" subtitle="Manual ideas still go through research and quality checks" />
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              className="input flex-1"
              placeholder="Topic"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void addManual();
              }}
            />
            <input className="input flex-1" placeholder="Angle (optional)" value={angle} onChange={(e) => setAngle(e.target.value)} />
            <button onClick={addManual} disabled={!topic.trim() || busy !== null} className="btn-ghost shrink-0">
              {busy === "manual" ? <Spinner /> : <Icon name="plus" className="h-4 w-4" strokeWidth={2.2} />}
              Add idea
            </button>
          </div>
        </Card>
      </Reveal>

      {loading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-[76px] w-full" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <Empty
          title={ideas.length === 0 ? "No ideas yet" : "No ideas match that filter"}
          body={
            ideas.length === 0
              ? "Generate one with the local model, or add your own topic. Ideas are fingerprinted so the same topic is not produced twice."
              : "Try a different search term."
          }
          icon="bulb"
          action={
            <button onClick={generate} className="btn-primary btn-sm">
              Generate first idea
            </button>
          }
        />
      ) : (
        <div className="space-y-2">
          <AnimatePresence initial={false} mode="popLayout">
            {filtered.map((idea) => (
              <motion.div
                key={idea.id}
                layout
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.98 }}
                transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
              >
                <Card className="card-hover">
                  <div className="flex flex-wrap items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-[13px] font-semibold text-white">{idea.topic}</h3>
                        <StatusChip status={idea.status} />
                        <span className="chip border-white/10 bg-white/5 text-slate-400">{idea.kind}</span>
                      </div>
                      {idea.angle && <p className="mt-1 text-[12px] leading-relaxed text-slate-400">{idea.angle}</p>}
                      <div className="mt-2 flex flex-wrap items-center gap-3 text-2xs text-slate-500">
                        <span className="flex items-center gap-1">
                          <Icon name="sparkles" className="h-2.5 w-2.5" />
                          novelty {idea.novelty_score !== null ? Math.round(idea.novelty_score) : "—"}
                        </span>
                        <span className="flex items-center gap-1">
                          <Icon name="shield" className="h-2.5 w-2.5" />
                          confidence {idea.confidence_score !== null ? Math.round(idea.confidence_score) : "—"}
                        </span>
                        <span className="flex items-center gap-1">
                          <Icon name="clock" className="h-2.5 w-2.5" />
                          {relTime(idea.created_at)}
                        </span>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      <button onClick={() => research(idea)} disabled={busy !== null} className="btn-ghost btn-sm">
                        {busy === `r-${idea.id}` ? <Spinner /> : "Research"}
                      </button>
                      <button onClick={() => writeScript(idea)} disabled={busy !== null} className="btn-ghost btn-sm">
                        {busy === `s-${idea.id}` ? <Spinner /> : "Write script"}
                      </button>
                      <Link to={`/scripts?idea=${idea.id}`} className="btn-ghost btn-sm">
                        <Icon name="doc" className="h-3 w-3" />
                        Studio
                      </Link>
                      <button onClick={() => enqueue(idea)} disabled={busy !== null} className="btn-primary btn-sm">
                        {busy === `q-${idea.id}` ? <Spinner /> : "Produce video"}
                      </button>
                      <button
                        onClick={() => remove(idea)}
                        disabled={busy !== null}
                        className="btn-danger btn-sm"
                        aria-label="Delete idea"
                      >
                        <Icon name="trash" className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                </Card>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
