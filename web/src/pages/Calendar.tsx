import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Card, Empty, PageHeader, Reveal, SectionTitle, StatusChip } from "../components/ui";
import { Icon } from "../components/icons";

type CalendarData = {
  planned_slots: { date: string; time: string; iso: string }[];
  scheduled_videos: { id: number; title: string; scheduled_at: string; status: string; youtube_video_id: string }[];
  ready_to_upload: { id: number; topic: string }[];
  timezone: string;
};

export default function Calendar() {
  const { notify } = useApp();
  const [data, setData] = useState<CalendarData | null>(null);

  useEffect(() => {
    api
      .get<CalendarData>("/api/dashboard/calendar")
      .then(setData)
      .catch((err: unknown) => notify("error", err instanceof Error ? err.message : "Failed to load calendar"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const grouped = (data?.planned_slots ?? []).reduce<Record<string, { time: string; iso: string }[]>>((acc, slot) => {
    acc[slot.date] = acc[slot.date] ?? [];
    acc[slot.date].push({ time: slot.time, iso: slot.iso });
    return acc;
  }, {});

  const today = new Date().toISOString().slice(0, 10);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Publish"
        title="Content calendar"
        subtitle={`Planned publishing slots for the next two weeks · time zone ${data?.timezone ?? "UTC"}`}
        actions={
          <span className="chip border-violet-500/25 bg-violet-500/10 text-violet-300">
            <Icon name="calendar" className="h-3 w-3" />
            {Object.keys(grouped).length} day{Object.keys(grouped).length === 1 ? "" : "s"}
          </span>
        }
      />

      <Reveal>
        <Card>
          <SectionTitle title="Upcoming slots" subtitle="Derived from your schedule settings" />
          {Object.keys(grouped).length === 0 ? (
            <Empty title="No slots scheduled" body="Enable automation and set publish times on the Automation page." icon="calendar" />
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {Object.entries(grouped).map(([date, slots], i) => {
                const isToday = date === today;
                return (
                  <motion.div
                    key={date}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.35, delay: Math.min(i * 0.03, 0.3), ease: [0.16, 1, 0.3, 1] }}
                    className={`rounded-xl border p-3 transition-colors ${
                      isToday ? "border-violet-500/35 bg-violet-500/[0.08]" : "border-white/[0.06] bg-white/[0.02] hover:border-white/[0.12]"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                        {new Date(date).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
                      </div>
                      {isToday && <span className="chip border-violet-500/30 bg-violet-500/15 text-[9px] text-violet-200">today</span>}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {slots.map((s) => (
                        <span key={s.iso} className="chip border-violet-500/25 bg-violet-500/10 text-violet-200">
                          <Icon name="clock" className="h-2.5 w-2.5" />
                          {s.time}
                        </span>
                      ))}
                    </div>
                  </motion.div>
                );
              })}
            </div>
          )}
        </Card>
      </Reveal>

      <div className="grid gap-5 lg:grid-cols-2">
        <Reveal delay={0.06}>
          <Card className="h-full">
            <SectionTitle title="Scheduled on YouTube" subtitle="Private uploads with a publish time" />
            <div className="space-y-2">
              {(data?.scheduled_videos ?? []).length === 0 && (
                <div className="rounded-xl border border-dashed border-white/[0.08] px-3 py-6 text-center text-[11px] text-slate-500">
                  Nothing scheduled yet.
                </div>
              )}
              {(data?.scheduled_videos ?? []).map((v) => (
                <div
                  key={v.id}
                  className="flex items-center gap-2 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2 transition-colors hover:border-white/[0.12]"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[11.5px] font-semibold text-slate-200">{v.title}</div>
                    <div className="text-2xs text-slate-500">
                      {v.scheduled_at ? new Date(v.scheduled_at).toLocaleString() : "no publish time"}
                    </div>
                  </div>
                  <StatusChip status={v.status} />
                </div>
              ))}
            </div>
          </Card>
        </Reveal>

        <Reveal delay={0.12}>
          <Card className="h-full">
            <SectionTitle title="Ready to upload" subtitle="Rendered and waiting for a slot" />
            <div className="space-y-2">
              {(data?.ready_to_upload ?? []).length === 0 && (
                <div className="rounded-xl border border-dashed border-white/[0.08] px-3 py-6 text-center text-[11px] text-slate-500">
                  Nothing ready.
                </div>
              )}
              {(data?.ready_to_upload ?? []).map((v) => (
                <div key={v.id} className="flex items-center gap-2 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2">
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                  <span className="truncate text-[11.5px] text-slate-300">{v.topic}</span>
                </div>
              ))}
            </div>
          </Card>
        </Reveal>
      </div>
    </div>
  );
}
