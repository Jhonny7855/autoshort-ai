import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import {
  Card,
  Empty,
  fmtNumber,
  PageHeader,
  relTime,
  Reveal,
  SectionTitle,
  Spinner,
  Stagger,
  StaggerItem,
  StatCard,
  StatusChip,
} from "../components/ui";
import { Icon } from "../components/icons";

type Video = {
  id: number;
  youtube_video_id: string;
  title: string;
  thumbnail: string | null;
  visibility: string;
  status: string;
  views: number;
  likes: number;
  comments: number;
  published_at: string | null;
  scheduled_at: string | null;
};

type Upload = {
  id: number;
  status: string;
  visibility: string;
  youtube_video_id: string | null;
  error: string | null;
  progress: number;
  created_at: string;
  script_title: string | null;
};

export default function Published() {
  const { notify } = useApp();
  const [videos, setVideos] = useState<Video[]>([]);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      const [v, u] = await Promise.all([
        api.get<{ videos: Video[] }>("/api/published"),
        api.get<{ uploads: Upload[] }>("/api/uploads"),
      ]);
      setVideos(v.videos);
      setUploads(u.uploads);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load library");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function sync() {
    setBusy("sync");
    try {
      const res = await api.post<{ synced: number }>("/api/published/sync");
      notify("success", `Synced ${res.synced} video(s) from YouTube`);
      await load();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Sync failed");
    } finally {
      setBusy(null);
    }
  }

  const totalViews = videos.reduce((s, v) => s + v.views, 0);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Publish"
        title="Published videos"
        subtitle="Real data from the YouTube Data API. Nothing is fabricated."
        actions={
          <button onClick={sync} disabled={busy !== null} className="btn-ghost">
            {busy === "sync" ? <Spinner /> : <Icon name="refresh" className="h-4 w-4" strokeWidth={1.9} />}
            Sync from YouTube
          </button>
        }
      />

      {videos.length > 0 && (
        <Stagger className="grid gap-3 sm:grid-cols-3">
          <StaggerItem>
            <StatCard label="Videos" value={videos.length} accent="violet" icon="bookmark" hint="Live on the channel" />
          </StaggerItem>
          <StaggerItem>
            <StatCard label="Total views" value={fmtNumber(totalViews)} accent="cyan" icon="eye" hint="Across all uploads" />
          </StaggerItem>
          <StaggerItem>
            <StatCard
              label="Upload attempts"
              value={uploads.length}
              accent={uploads.some((u) => u.error) ? "amber" : "emerald"}
              icon="upload"
              hint={`${uploads.filter((u) => u.error).length} with errors`}
            />
          </StaggerItem>
        </Stagger>
      )}

      {videos.length === 0 ? (
        <Empty
          title="No videos published yet"
          body="Once an upload succeeds, the video appears here with live statistics. If you publish manually, mark it in the Publishing queue."
          icon="bookmark"
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {videos.map((v, i) => (
            <Reveal key={v.id} delay={Math.min(i * 0.04, 0.28)}>
              <Card className="card-hover group overflow-hidden p-0">
                <a
                  href={`https://www.youtube.com/watch?v=${v.youtube_video_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="block"
                >
                  <div className="relative aspect-video overflow-hidden bg-ink-800">
                    {v.thumbnail ? (
                      <img
                        src={v.thumbnail}
                        alt=""
                        className="h-full w-full object-cover transition-transform duration-500 ease-smooth group-hover:scale-105"
                      />
                    ) : (
                      <div className="grid h-full place-items-center text-[10px] text-slate-600">no thumbnail</div>
                    )}
                    <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
                    <span className="absolute bottom-2 right-2 grid h-7 w-7 place-items-center rounded-full bg-black/60 text-white opacity-0 backdrop-blur transition-all duration-300 group-hover:opacity-100">
                      <Icon name="external" className="h-3.5 w-3.5" strokeWidth={2} />
                    </span>
                  </div>
                </a>
                <div className="p-3.5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="line-clamp-2 text-[11.5px] font-semibold leading-snug text-slate-200">{v.title}</div>
                    <StatusChip status={v.status} />
                  </div>
                  <div className="mt-2.5 grid grid-cols-3 gap-1.5 text-center">
                    {[
                      ["Views", fmtNumber(v.views)],
                      ["Likes", fmtNumber(v.likes)],
                      ["Comments", fmtNumber(v.comments)],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded-md bg-white/[0.03] py-1">
                        <div className="text-[9px] uppercase tracking-wider text-slate-600">{label}</div>
                        <div className="numeric text-[11px] font-semibold text-slate-300">{value}</div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-2 flex items-center justify-between text-2xs text-slate-500">
                    <span className="capitalize">{v.visibility}</span>
                    <span>{relTime(v.published_at ?? v.scheduled_at)}</span>
                  </div>
                </div>
              </Card>
            </Reveal>
          ))}
        </div>
      )}

      <Reveal delay={0.1}>
        <Card>
          <SectionTitle title="Upload history" subtitle="Every attempt with real status and errors" />
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-2xs uppercase tracking-wider text-slate-600">
                  <th className="pb-2.5 pr-3 font-bold">Title</th>
                  <th className="pb-2.5 pr-3 font-bold">Status</th>
                  <th className="pb-2.5 pr-3 font-bold">Visibility</th>
                  <th className="pb-2.5 pr-3 font-bold">Video id</th>
                  <th className="pb-2.5 pr-3 font-bold">When</th>
                  <th className="pb-2.5 font-bold">Error</th>
                </tr>
              </thead>
              <tbody>
                {uploads.map((u) => (
                  <tr key={u.id} className="table-row">
                    <td className="max-w-[240px] truncate py-2 pr-3 text-slate-300">{u.script_title ?? "—"}</td>
                    <td className="py-2 pr-3">
                      <StatusChip status={u.status} />
                    </td>
                    <td className="py-2 pr-3 capitalize text-slate-400">{u.visibility}</td>
                    <td className="py-2 pr-3 font-mono text-[10px] text-slate-500">{u.youtube_video_id ?? "—"}</td>
                    <td className="py-2 pr-3 text-slate-500">{relTime(u.created_at)}</td>
                    <td className="max-w-[220px] truncate py-2 text-rose-300">{u.error ?? ""}</td>
                  </tr>
                ))}
                {uploads.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-6 text-center text-slate-500">
                      No uploads yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </Reveal>
    </div>
  );
}
