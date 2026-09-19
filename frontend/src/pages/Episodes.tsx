import { useEffect, useState } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { api } from "../api";
import { useQueue } from "../context/QueueContext";
import ConfirmModal from "../components/ConfirmModal";

interface Episode {
  id: number;
  episodeNumber: number;
  title: string;
  hasFile: boolean;
  episodeFileId: number;
  fileName?: string;
  fileSize?: number;
  quality?: string;
  watched?: boolean;
}

export default function Episodes() {
  const { id, season } = useParams<{ id: string; season: string }>();
  const location = useLocation();
  const seriesTitle = (location.state as any)?.title || "";
  const seriesPoster = (location.state as any)?.poster || "";
  const { isInProgress, refreshKey, markPending, clearPending, setExpanded } = useQueue();
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmEp, setConfirmEp] = useState<Episode | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!id || !season) return;
    api.episodes(Number(id), Number(season))
      .then(setEpisodes)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id, season, refreshKey]);

  if (loading) return <div className="p-5 text-gray-500">Loading...</div>;

  return (
    <div className="p-5">
      <button onClick={() => navigate(-1)} className="text-gray-400 text-sm mb-3 hover:text-white transition">
        ← Back
      </button>
      <div className="flex gap-4 mb-5">
        {seriesPoster && (
          <img src={seriesPoster} alt="" className="w-20 h-28 object-cover rounded-lg shrink-0" loading="lazy" />
        )}
        <div>
          {seriesTitle && <h2 className="text-lg font-semibold">{seriesTitle}</h2>}
          <p className="text-sm text-gray-500 mt-1">Season {season}</p>
        </div>
      </div>
      <div className="space-y-2">
        {episodes.map((ep) => {
          const fixing = isInProgress("episode", ep.id);
          const canFix = ep.hasFile && !fixing;
          const canGrab = !ep.hasFile && !fixing;
          const handleFixClick = (ep: Episode) => {
            setConfirmEp(ep);
          };
          const handleGrabClick = async (ep: Episode) => {
            markPending("episode", ep.id);
            try {
              await api.fix({
                type: "episode",
                episodeId: ep.id,
                fileId: 0,
                seriesId: Number(id),
                seasonNumber: Number(season),
                title: `${seriesTitle ? seriesTitle + " " : ""}S${season}E${String(ep.episodeNumber).padStart(2, "0")}: ${ep.title}`,
              });
              setExpanded(true);
            } catch {
              clearPending("episode", ep.id);
            }
          };
          return (
          <div
            key={ep.id}
            onClick={() => canFix ? handleFixClick(ep) : canGrab ? handleGrabClick(ep) : undefined}
            className={`bg-card rounded-xl p-4 flex justify-between items-center border transition ${
              fixing ? "border-purple-500/30 opacity-70" :
              (canFix || canGrab) ? "border-white/5 cursor-pointer hover:border-purple-500/30" :
              "border-white/5 opacity-60"
            }`}
          >
            <div className="flex-1 min-w-0">
              <div className="font-medium text-sm flex items-center gap-1.5">
                {ep.watched && (
                  <span title="Watched" className="text-emerald-400 shrink-0" aria-label="Watched">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
                      <path fillRule="evenodd" d="M16.704 5.29a1 1 0 010 1.42l-8 8a1 1 0 01-1.41 0l-4-4a1 1 0 111.41-1.42L8 12.59l7.293-7.3a1 1 0 011.41 0z" clipRule="evenodd" />
                    </svg>
                  </span>
                )}
                <span className="truncate">E{String(ep.episodeNumber).padStart(2, "0")}: {ep.title}</span>
              </div>
              {fixing ? (
                <div className="text-xs text-purple-400 mt-1 flex items-center gap-1.5">
                  <div className="w-3 h-3 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
                  Fix in progress...
                </div>
              ) : ep.hasFile ? (
                <div className="text-xs text-emerald-400 mt-1">
                  {ep.quality || "Unknown"} · {((ep.fileSize || 0) / 1073741824).toFixed(1)} GB
                </div>
              ) : (
                <div className="text-xs text-red-400 mt-1">No file</div>
              )}
            </div>
            {fixing ? (
              <span className="ml-3 px-3 py-1.5 rounded-lg bg-purple-600/50 text-xs font-semibold shrink-0 text-purple-300">
                Fixing
              </span>
            ) : ep.hasFile ? (
              <span className="ml-3 px-3 py-1.5 rounded-lg bg-red-600 text-xs font-semibold shrink-0">
                Fix
              </span>
            ) : !fixing ? (
              <span className="ml-3 px-3 py-1.5 rounded-lg bg-indigo-600 text-xs font-semibold shrink-0">
                Grab
              </span>
            ) : null}
          </div>
          );
        })}
      </div>

      {confirmEp && (
        <ConfirmModal
          type="episode"
          title={`${seriesTitle ? seriesTitle + " — " : ""}S${season}E${String(confirmEp.episodeNumber).padStart(2, "0")}: ${confirmEp.title}`}
          subtitle={`Season ${season}`}
          fileName={confirmEp.fileName || ""}
          fileSize={confirmEp.fileSize || 0}
          quality={confirmEp.quality || ""}
          poster={seriesPoster}
          fixPayload={{
            type: "episode",
            episodeId: confirmEp.id,
            fileId: confirmEp.episodeFileId,
            seriesId: Number(id),
            seasonNumber: Number(season),
            title: `${seriesTitle ? seriesTitle + " " : ""}S${season}E${String(confirmEp.episodeNumber).padStart(2, "0")}: ${confirmEp.title}`,
          }}
          watched={!!confirmEp.watched}
          onClose={() => setConfirmEp(null)}
        />
      )}
    </div>
  );
}
