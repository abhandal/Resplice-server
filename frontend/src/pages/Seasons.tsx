import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";

interface Season {
  season: number;
  episodeCount: number;
  hasFiles: number;
  watchedCount?: number;
  status?: string | null;
}

export default function Seasons() {
  const { user } = useAuth();
  const { id } = useParams<{ id: string }>();
  const [title, setTitle] = useState("");
  const [poster, setPoster] = useState("");
  const [tmdbId, setTmdbId] = useState<number | null>(null);
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    if (!id) return;
    api.seasons(Number(id))
      .then((data) => {
        setTitle(data.title);
        setPoster(data.poster || "");
        setTmdbId(data.tmdbId || null);
        setSeasons(data.seasons);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="p-5 text-gray-500">Loading...</div>;

  const overseerrUrl = tmdbId && user?.requestUrl ? `${user.requestUrl}/tv/${tmdbId}` : null;

  return (
    <div className="p-5">
      <button onClick={() => navigate(-1)} className="text-gray-400 text-sm mb-3 hover:text-white transition">
        ← Back
      </button>
      <div className="flex gap-4 mb-5">
        {poster && (
          <img src={poster} alt="" className="w-20 h-28 object-cover rounded-lg shrink-0" loading="lazy" />
        )}
        <div>
          <h2 className="text-lg font-semibold">{title}</h2>
          <p className="text-sm text-gray-500 mt-1">Pick a season</p>
        </div>
      </div>
      <div className="space-y-2">
        {seasons.filter((s) => s.season > 0).map((s) => {
          const notAired = s.status === "TBA" || (s.status && s.status !== "missing");
          const missing = s.status === "missing";
          const clickable = !notAired && !missing;
          if (missing && overseerrUrl) {
            return (
              <a
                key={s.season}
                href={overseerrUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="bg-card rounded-xl p-4 flex justify-between items-center border border-white/5 cursor-pointer hover:border-indigo-500/30 transition block"
              >
                <span className="font-medium">Season {s.season}</span>
                <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-indigo-500/20 text-indigo-400">
                  Request Season →
                </span>
              </a>
            );
          }
          return (
            <div
              key={s.season}
              onClick={() => clickable && navigate(`/series/${id}/season/${s.season}`, { state: { title, poster } })}
              className={`bg-card rounded-xl p-4 flex justify-between items-center border transition ${
                notAired ? "border-white/5 opacity-50" : "border-white/5 cursor-pointer hover:border-purple-500/30"
              }`}
            >
              <span className="font-medium flex items-center gap-1.5">
                {!!s.watchedCount && s.watchedCount >= s.episodeCount && s.episodeCount > 0 && (
                  <span title="Fully watched" className="text-emerald-400">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
                      <path fillRule="evenodd" d="M16.704 5.29a1 1 0 010 1.42l-8 8a1 1 0 01-1.41 0l-4-4a1 1 0 111.41-1.42L8 12.59l7.293-7.3a1 1 0 011.41 0z" clipRule="evenodd" />
                    </svg>
                  </span>
                )}
                Season {s.season}
              </span>
              {notAired ? (
                <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-amber-500/20 text-amber-400">
                  {s.status === "TBA" ? "TBA" : s.status}
                </span>
              ) : (
                <span className="text-sm text-gray-500">
                  {s.hasFiles}/{s.episodeCount} eps
                  {s.watchedCount ? ` · ${s.watchedCount} watched` : ""}
                  {" · →"}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
