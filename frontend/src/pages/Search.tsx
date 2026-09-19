import { useState, useEffect, useRef } from "react";

import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useQueue } from "../context/QueueContext";
import { useAuth } from "../context/AuthContext";
import ConfirmModal from "../components/ConfirmModal";
import StatsCard from "../components/StatsCard";

interface SearchResult {
  type: "series" | "movie";
  id: number;
  tmdbId?: number;
  title: string;
  year: number;
  seasonCount?: number;
  hasFile?: boolean;
  fileId?: number;
  fileSize?: number;
  quality?: string;
  genres?: string[];
  poster?: string;
  library?: string;
  watched?: boolean;
}

const WatchedBadge = () => (
  <span title="Watched" className="text-emerald-400 shrink-0" aria-label="Watched">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
      <path fillRule="evenodd" d="M16.704 5.29a1 1 0 010 1.42l-8 8a1 1 0 01-1.41 0l-4-4a1 1 0 111.41-1.42L8 12.59l7.293-7.3a1 1 0 011.41 0z" clipRule="evenodd" />
    </svg>
  </span>
);

const LIBRARY_ORDER = ["Movies", "TV Shows", "Anime"];

function groupByLibrary(items: SearchResult[]): [string, SearchResult[]][] {
  const groups = new Map<string, SearchResult[]>();
  for (const item of items) {
    const lib = item.library || "Other";
    if (!groups.has(lib)) groups.set(lib, []);
    groups.get(lib)!.push(item);
  }
  return Array.from(groups.entries()).sort(([a], [b]) => {
    const ai = LIBRARY_ORDER.indexOf(a);
    const bi = LIBRARY_ORDER.indexOf(b);
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });
}

export default function Search() {
  const { user } = useAuth();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [recentlyWatched, setRecentlyWatched] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [recentLoading, setRecentLoading] = useState(true);
  const [confirmMovie, setConfirmMovie] = useState<SearchResult | null>(null);
  const [rateInfo, setRateInfo] = useState<any>(null);
  const navigate = useNavigate();
  const { isInProgress } = useQueue();
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    api.rateLimit().then(setRateInfo).catch(() => {});
    api.recentlyWatched()
      .then(setRecentlyWatched)
      .catch(() => {})
      .finally(() => setRecentLoading(false));
  }, []);

  const doSearch = async (q: string) => {
    if (q.trim().length < 3) return;
    setLoading(true);
    try {
      const data = await api.search(q);
      setResults(data);
    } catch (e: any) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (query.trim().length < 3) {
      setResults([]);
      return;
    }
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(query), 100);
    return () => clearTimeout(debounceRef.current);
  }, [query]);

  const handleClick = (item: SearchResult) => {
    if (item.type === "series") {
      navigate(`/series/${item.id}`);
    } else if (item.hasFile && !isInProgress("movie", item.id)) {
      setConfirmMovie(item);
    } else if (item.type === "movie" && !item.hasFile && item.tmdbId && user?.requestUrl) {
      window.open(`${user.requestUrl}/movie/${item.tmdbId}`, "_blank");
    }
  };

  return (
    <div className="p-5">
      {!results.length && !query && (
        <div className="mb-6 bg-white/5 rounded-xl p-4 text-sm text-gray-400">
          <p className="font-medium text-white mb-2">How it works</p>
          <ol className="list-decimal list-inside space-y-1.5">
            <li>Search for the show or movie</li>
            <li>For TV shows, tap the series then pick a season</li>
            <li>Tap <span className="text-red-400 font-medium">Fix</span> to replace a broken file, or <span className="text-indigo-400 font-medium">Grab</span> to download a missing episode</li>
            <li>Choose <span className="text-red-400 font-medium">Auto Fix</span> for a quick replacement, or <span className="text-purple-400 font-medium">Manual Fix</span> to pick a specific version yourself</li>
            <li>Track progress in your queue at the bottom — refresh Infuse when it's ready</li>
          </ol>
          <p className="mt-3 text-xs text-gray-500">
            If Auto Fix doesn't work, come back to the same episode and the app will suggest Manual Fix so you can choose a different version.
            Missing a whole season or movie? Tap <span className="text-indigo-400 font-medium">Request</span> to request it on Overseerr — you'll get an email when it's available.
          </p>
          <p className="mt-2 text-xs text-gray-500">
            {rateInfo?.remaining === -1
              ? "You have unlimited fix requests."
              : `You have ${rateInfo?.maxPerDay ?? 10} fix requests per day with a ${Math.round((rateInfo?.cooldown ?? 60) / 60)}-minute cooldown between each.`}
          </p>
        </div>
      )}
      <div className="mb-6 relative">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search movies & shows..."
          autoFocus
          className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 pr-10 text-white placeholder-gray-500 focus:outline-none focus:border-purple-500/50 transition"
        />
        {query && !loading && (
          <button
            onClick={() => setQuery("")}
            className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white transition"
          >
            ×
          </button>
        )}
        {loading && (
          <div className="absolute right-4 top-1/2 -translate-y-1/2">
            <div className="w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
          </div>
        )}
      </div>

      {/* Watch-time stats — always above recently-watched on the home view */}
      {!query && !results.length && <StatsCard />}

      {/* Recently watched — shown when no search query, grouped by Plex library */}
      {!query && !results.length && recentlyWatched.length > 0 && (
        <div className="mb-4 space-y-5">
          {groupByLibrary(recentlyWatched).map(([library, items]) => (
            <div key={library}>
              <p className="text-sm font-medium text-gray-400 mb-3">Recently watched · {library}</p>
              <div className="space-y-3">
                {items.slice(0, 8).map((item) => {
                  const fixing = item.type === "movie" && isInProgress("movie", item.id);
                  return (
                    <div
                      key={`recent-${item.type}-${item.id}`}
                      onClick={() => handleClick(item)}
                      className={`rounded-xl overflow-hidden border bg-card flex transition ${
                        fixing ? "border-purple-500/30 opacity-70" : "border-white/5 cursor-pointer hover:border-purple-500/30"
                      }`}
                    >
                      {item.poster && (
                        <img src={item.poster} alt="" className="w-16 h-24 object-cover shrink-0" loading="lazy" />
                      )}
                      <div className="flex-1 flex items-center justify-between px-4 py-3 min-w-0">
                        <div className="min-w-0">
                          <div className="font-semibold flex items-center gap-1.5 min-w-0">
                            {item.type === "movie" && item.watched && <WatchedBadge />}
                            <span className="truncate">{item.title}</span>
                          </div>
                          <div className="text-xs text-gray-500 mt-0.5">
                            {item.year}
                            {item.type === "series" ? ` · TV` : " · Movie"}
                          </div>
                        </div>
                        <span className="text-white/20 text-lg ml-2 shrink-0">→</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
      {!query && !results.length && recentLoading && (
        <div className="flex justify-center py-8">
          <div className="w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      <div className="space-y-3">
        {results.map((item) => {
          const fixing = item.type === "movie" && isInProgress("movie", item.id);
          return (
          <div
            key={`${item.type}-${item.id}`}
            onClick={() => handleClick(item)}
            className={`rounded-xl overflow-hidden border bg-card flex transition ${
              fixing ? "border-purple-500/30 opacity-70" : "border-white/5 cursor-pointer hover:border-purple-500/30"
            }`}
          >
            {item.poster && (
              <img
                src={item.poster}
                alt=""
                className="w-16 h-24 object-cover shrink-0"
                loading="lazy"
              />
            )}
            <div className="flex-1 flex items-center justify-between px-4 py-3 min-w-0">
              <div className="min-w-0">
                <div className="font-semibold flex items-center gap-1.5 min-w-0">
                  {item.type === "movie" && item.watched && <WatchedBadge />}
                  <span className="truncate">{item.title}</span>
                </div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {item.year}
                  {item.type === "series" ? ` · ${item.seasonCount} Seasons · TV` : " · Movie"}
                  {item.genres?.length ? ` · ${item.genres.join(", ")}` : ""}
                </div>
              </div>
              {item.type === "series" ? (
                <span className="text-white/20 text-lg ml-2 shrink-0">→</span>
              ) : fixing ? (
                <span className="px-3 py-1.5 rounded-lg bg-purple-600/50 text-xs font-semibold ml-2 shrink-0 text-purple-300 flex items-center gap-1.5">
                  <div className="w-3 h-3 border-2 border-purple-300 border-t-transparent rounded-full animate-spin" />
                  Fixing
                </span>
              ) : item.hasFile ? (
                <span className="px-3 py-1.5 rounded-lg bg-red-600 text-xs font-semibold ml-2 shrink-0">Fix</span>
              ) : item.type === "movie" && !item.hasFile && item.tmdbId && user?.requestUrl ? (
                <a
                  href={`${user.requestUrl}/movie/${item.tmdbId}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="px-3 py-1.5 rounded-lg bg-indigo-500/20 text-indigo-400 text-xs font-semibold ml-2 shrink-0 hover:bg-indigo-500/30 transition"
                >
                  Request →
                </a>
              ) : null}
            </div>
          </div>
          );
        })}
      </div>

      {confirmMovie && (
        <ConfirmModal
          type="movie"
          title={confirmMovie.title}
          subtitle={`${confirmMovie.year} · Movie`}
          fileName=""
          fileSize={confirmMovie.fileSize || 0}
          quality={confirmMovie.quality || ""}
          poster={confirmMovie.poster}
          fixPayload={{
            type: "movie",
            movieId: confirmMovie.id,
            fileId: confirmMovie.fileId,
            title: confirmMovie.title,
          }}
          onClose={() => setConfirmMovie(null)}
        />
      )}
    </div>
  );
}
