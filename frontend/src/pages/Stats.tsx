import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";

interface ByType {
  library: string;
  type: string;
  seconds: number;
  plays: number;
}

interface Period {
  seconds: number;
  plays: number;
  duration: { compact: string; fun: string; hours: number; days: number };
  tier: { label: string; blurb: string };
  playsLabel: string;
  byType: ByType[];
}

interface MediaRow {
  title: string;
  year?: number;
  plays: number;
  seconds?: number;
  ratingKey?: string;
  thumb?: string;
  episodesWatched?: number;  // present when source = "plex"
}

interface PlatformRow {
  platform: string;
  plays: number;
  seconds: number;
}

interface LibraryRow {
  sectionId: number;
  library: string;
  type: string;
  noun: string;
  total: number;
  watched: number;
  verb: string;
  pct: number;
  blurb: string;
}

interface DayBreakdown {
  day: string;
  plays: number;
  byLibrary: { library: string; plays: number }[];
}

interface FunStats {
  topGenres?: { name: string; seconds: number }[];
  topNetworks?: { name: string; seconds: number }[];
  topLanguages?: { name: string; seconds: number }[];
  decades?: { decade: number; seconds: number }[];
  avgMovieRuntimeMin?: number;
  yourYear?: { year: number; seconds: number } | null;
  comfortShow?: { title: string; plays: number; seconds: number } | null;
  powerDay?: { date: string; seconds: number; plays: number };
  streaks?: { longest: number; current: number; longestEndDate: string };
  rewatch?: { firstTime: number; rewatches: number; ratio: number };
  byDayOfWeek?: DayBreakdown[];
}

const LIBRARY_COLORS: Record<string, string> = {
  "Movies": "bg-indigo-400",
  "TV Shows": "bg-purple-400",
  "Anime": "bg-pink-400",
  "Other": "bg-slate-400",
};

interface DetailedResp {
  period: string;
  days: number;
  periods: { "30days": Period; "90days": Period; ytd: Period; allTime: Period };
  topShows: MediaRow[];
  topShowsSource: "tautulli" | "plex";
  topMovies: MediaRow[];
  topMoviesSource: "tautulli" | "plex";
  topPlatforms: PlatformRow[];
  libraries: LibraryRow[];
  fun?: FunStats;
}

const PERIOD_OPTIONS: { key: string; label: string }[] = [
  { key: "30days", label: "30 Days" },
  { key: "90days", label: "90 Days" },
  { key: "ytd", label: "YTD" },
  { key: "allTime", label: "All Time" },
];

const fmtNum = (n: number) => n.toLocaleString();

const fmtHours = (s: number) => {
  const h = s / 3600;
  if (h < 1) return `${Math.round(s / 60)}m`;
  if (h < 100) return `${h.toFixed(1)}h`;
  return `${fmtNum(Math.round(h))}h`;
};

const PLATFORM_QUIPS: Record<string, string> = {
  Android: "Pocket-cinema main character",
  tvOS: "Couch-and-Apple-TV traditionalist",
  iPadOS: "Bathtub philosopher",
  iOS: "Public transit theatre",
  webOS: "TV-of-mystery enjoyer",
  Roku: "Set-it-and-forget-it era",
  Chrome: "Browser-tab archaeologist",
  "Mac OSX": "Productive procrastinator",
};

const platformQuip = (platform: string) =>
  PLATFORM_QUIPS[platform] || "Multi-screen drifter";

function CardLoading() {
  return <div className="rounded-2xl border border-white/5 bg-card animate-pulse h-32" />;
}

export default function Stats() {
  const [params, setParams] = useSearchParams();
  const initial = params.get("period") || "30days";
  const [period, setPeriod] = useState(initial);
  const [data, setData] = useState<DetailedResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    setError("");
    setSelectedDay(null);
    api.statsDetailed(period)
      .then(setData)
      .catch((e) => setError(e.message || "Failed to load stats"))
      .finally(() => setLoading(false));
    setParams({ period }, { replace: true });
  }, [period]);

  const current = data?.periods[period as keyof DetailedResp["periods"]];
  const totalShowSeconds = data?.topShows.reduce((s, x) => s + (x.seconds || 0), 0) || 0;
  const totalMovieSeconds = data?.topMovies.reduce((s, x) => s + (x.seconds || 0), 0) || 0;
  const totalShowEps = data?.topShows.reduce((s, x) => s + (x.episodesWatched || 0), 0) || 0;
  const totalMoviePlays = data?.topMovies.reduce((s, x) => s + (x.plays || 0), 0) || 0;
  const showsFromPlex = data?.topShowsSource === "plex";
  const moviesFromPlex = data?.topMoviesSource === "plex";

  return (
    <div className="p-5">
      <button onClick={() => navigate(-1)} className="text-gray-400 text-sm mb-3 hover:text-white transition">
        ← Back
      </button>
      <h2 className="text-lg font-semibold mb-1">Your watch stats</h2>
      <p className="text-sm text-gray-500 mb-4">No judgment, just receipts.</p>

      {/* Period switcher */}
      <div className="grid grid-cols-4 gap-2 mb-5">
        {PERIOD_OPTIONS.map((p) => {
          const isActive = period === p.key;
          return (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={`py-2 rounded-xl text-xs font-medium border transition ${
                isActive
                  ? "border-purple-500/60 bg-purple-500/15 text-white"
                  : "border-white/5 text-gray-400 hover:border-white/15 hover:text-gray-200"
              }`}
            >
              {p.label}
            </button>
          );
        })}
      </div>

      {error && <div className="text-red-400 text-sm mb-4">{error}</div>}

      {loading && (
        <div className="space-y-4">
          <CardLoading />
          <CardLoading />
          <CardLoading />
        </div>
      )}

      {!loading && data && current && (
        <>
          {/* Hero summary */}
          <div className="rounded-2xl border border-white/5 bg-gradient-to-br from-purple-500/10 via-card to-card p-5 mb-4">
            <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
              {PERIOD_OPTIONS.find((o) => o.key === period)?.label}
            </div>
            <div className="flex items-baseline gap-3">
              <div className="text-5xl font-bold tabular-nums">{current.duration.compact}</div>
              <div className="text-sm text-gray-500">{current.playsLabel}</div>
            </div>
            {current.byType?.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {current.byType.map((b) => (
                  <span
                    key={b.library}
                    className="px-2 py-1 rounded-md bg-white/5 text-xs text-gray-300 tabular-nums"
                  >
                    <span className="font-semibold">{fmtHours(b.seconds)}</span>
                    <span className="text-gray-500 ml-1">{b.library.toLowerCase()}</span>
                  </span>
                ))}
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
              <span className="px-2.5 py-1 rounded-lg bg-purple-500/20 text-purple-200 text-xs font-semibold">
                {current.tier.label}
              </span>
              <span className="text-gray-400">{current.duration.fun}</span>
            </div>
            <p className="text-sm text-gray-300 mt-3 italic">{current.tier.blurb}</p>
          </div>

          {/* Fun stats — derived from cross-server Plex history + Sonarr/Radarr metadata */}
          {data.fun && Object.keys(data.fun).length > 0 && (
            <div className="mb-4 space-y-3">
              <h3 className="text-sm font-medium text-gray-400 px-1">For your amusement</h3>

              {/* 2x2 mini-card grid */}
              <div className="grid grid-cols-2 gap-3">
                {data.fun.comfortShow && (
                  <div className="rounded-xl border border-white/5 bg-card p-3">
                    <div className="text-[10px] uppercase tracking-wider text-gray-500">Comfort show</div>
                    <div className="font-semibold mt-1 truncate" title={data.fun.comfortShow.title}>{data.fun.comfortShow.title}</div>
                    <div className="text-xs text-gray-400 mt-0.5 tabular-nums">{fmtNum(data.fun.comfortShow.plays)} plays · {fmtHours(data.fun.comfortShow.seconds)}</div>
                  </div>
                )}
                {data.fun.streaks && data.fun.streaks.longest > 1 && (
                  <div className="rounded-xl border border-white/5 bg-card p-3">
                    <div className="text-[10px] uppercase tracking-wider text-gray-500">Longest streak</div>
                    <div className="font-semibold mt-1">{fmtNum(data.fun.streaks.longest)} days</div>
                    <div className="text-xs text-gray-400 mt-0.5">
                      ended {data.fun.streaks.longestEndDate}
                      {data.fun.streaks.current > 0 && ` · ${data.fun.streaks.current}-day active`}
                    </div>
                  </div>
                )}
                {data.fun.powerDay && data.fun.powerDay.plays > 0 && (
                  <div className="rounded-xl border border-white/5 bg-card p-3">
                    <div className="text-[10px] uppercase tracking-wider text-gray-500">Biggest binge day</div>
                    <div className="font-semibold mt-1">{fmtNum(data.fun.powerDay.plays)} plays</div>
                    <div className="text-xs text-gray-400 mt-0.5">on {data.fun.powerDay.date}</div>
                  </div>
                )}
                {data.fun.rewatch && data.fun.rewatch.ratio > 0 && (
                  <div className="rounded-xl border border-white/5 bg-card p-3">
                    <div className="text-[10px] uppercase tracking-wider text-gray-500">Rewatch rate</div>
                    <div className="font-semibold mt-1">{data.fun.rewatch.ratio}%</div>
                    <div className="text-xs text-gray-400 mt-0.5 tabular-nums">{fmtNum(data.fun.rewatch.rewatches)} repeat plays</div>
                  </div>
                )}
                {data.fun.yourYear && (
                  <div className="rounded-xl border border-white/5 bg-card p-3">
                    <div className="text-[10px] uppercase tracking-wider text-gray-500">Your year</div>
                    <div className="font-semibold mt-1">{data.fun.yourYear.year}</div>
                    <div className="text-xs text-gray-400 mt-0.5">{fmtHours(data.fun.yourYear.seconds)} from this year alone</div>
                  </div>
                )}
                {!!data.fun.avgMovieRuntimeMin && (
                  <div className="rounded-xl border border-white/5 bg-card p-3">
                    <div className="text-[10px] uppercase tracking-wider text-gray-500">Avg movie length</div>
                    <div className="font-semibold mt-1">{Math.floor(data.fun.avgMovieRuntimeMin / 60)}h {data.fun.avgMovieRuntimeMin % 60}m</div>
                    <div className="text-xs text-gray-400 mt-0.5">your sweet spot</div>
                  </div>
                )}
              </div>

              {/* Top genres */}
              {data.fun.topGenres && data.fun.topGenres.length > 0 && (
                <div className="rounded-2xl border border-white/5 bg-card p-5">
                  <h3 className="font-semibold mb-3">Top genres</h3>
                  <div className="space-y-1.5">
                    {data.fun.topGenres.map((g, i) => {
                      const max = data.fun!.topGenres![0].seconds || 1;
                      const pct = (g.seconds / max) * 100;
                      return (
                        <div key={g.name} className="relative rounded-md overflow-hidden">
                          <div className="absolute inset-y-0 left-0 bg-pink-500/15" style={{ width: `${pct}%` }} />
                          <div className="relative flex items-center justify-between px-3 py-1.5 text-sm">
                            <span><span className="text-gray-500 text-xs mr-2">{i + 1}</span>{g.name}</span>
                            <span className="text-xs text-gray-400 tabular-nums">{fmtHours(g.seconds)}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Day of week — stacked by library, tap a bar to see the breakdown */}
              {data.fun.byDayOfWeek && data.fun.byDayOfWeek.some((b) => b.plays > 0) && (
                <div className="rounded-2xl border border-white/5 bg-card p-5">
                  <div className="flex items-baseline justify-between mb-3">
                    <h3 className="font-semibold">By day of week</h3>
                    <span className="text-[10px] text-gray-500 uppercase tracking-wider">plays · tap a bar</span>
                  </div>
                  <div className="flex items-end justify-between gap-2">
                    {data.fun.byDayOfWeek.map((b) => {
                      const max = Math.max(...data.fun!.byDayOfWeek!.map((x) => x.plays)) || 1;
                      const h = Math.max(6, (b.plays / max) * 96);
                      const isActive = selectedDay === b.day;
                      return (
                        <button
                          key={b.day}
                          type="button"
                          onClick={() => setSelectedDay(isActive ? null : b.day)}
                          className={`flex-1 flex flex-col items-center gap-1.5 transition ${isActive ? "" : "opacity-90 hover:opacity-100"}`}
                        >
                          <div className="text-[10px] text-gray-400 tabular-nums">{fmtNum(b.plays)}</div>
                          <div
                            className={`w-full rounded-t-md overflow-hidden flex flex-col-reverse border ${isActive ? "border-white/30" : "border-transparent"}`}
                            style={{ height: `${h}px` }}
                          >
                            {b.byLibrary.length === 0 && <div className="w-full h-full bg-white/5" />}
                            {b.byLibrary.map((seg) => {
                              const color = LIBRARY_COLORS[seg.library] || "bg-slate-500";
                              const pct = b.plays ? (seg.plays / b.plays) * 100 : 0;
                              return (
                                <div
                                  key={seg.library}
                                  title={`${seg.library}: ${fmtNum(seg.plays)} plays`}
                                  className={`${color} opacity-80`}
                                  style={{ height: `${pct}%` }}
                                />
                              );
                            })}
                          </div>
                          <div className={`text-[10px] ${isActive ? "text-white font-semibold" : "text-gray-500"}`}>{b.day}</div>
                        </button>
                      );
                    })}
                  </div>
                  {/* Legend */}
                  <div className="flex flex-wrap gap-3 text-[10px] text-gray-400 mt-3">
                    {["Movies", "TV Shows", "Anime", "Other"].map((lib) => (
                      <span key={lib} className="flex items-center gap-1.5">
                        <span className={`w-2.5 h-2.5 rounded-sm ${LIBRARY_COLORS[lib]} opacity-80`} />
                        {lib}
                      </span>
                    ))}
                  </div>
                  {/* Tap-to-expand detail */}
                  {selectedDay && (() => {
                    const day = data.fun!.byDayOfWeek!.find((d) => d.day === selectedDay);
                    if (!day) return null;
                    return (
                      <div className="mt-4 pt-4 border-t border-white/5">
                        <div className="flex items-baseline justify-between mb-2">
                          <span className="text-sm font-semibold">{day.day}</span>
                          <span className="text-xs text-gray-500 tabular-nums">{fmtNum(day.plays)} plays total</span>
                        </div>
                        <div className="space-y-1.5">
                          {day.byLibrary.map((seg) => {
                            const pct = day.plays ? Math.round((seg.plays / day.plays) * 100) : 0;
                            return (
                              <div key={seg.library} className="flex items-center justify-between text-xs">
                                <span className="flex items-center gap-2">
                                  <span className={`w-2 h-2 rounded-sm ${LIBRARY_COLORS[seg.library] || "bg-slate-500"} opacity-80`} />
                                  <span className="text-gray-300">{seg.library}</span>
                                </span>
                                <span className="text-gray-400 tabular-nums">{fmtNum(seg.plays)} · {pct}%</span>
                              </div>
                            );
                          })}
                          {day.byLibrary.length === 0 && (
                            <p className="text-xs text-gray-500 italic">Quiet day — nothing watched.</p>
                          )}
                        </div>
                      </div>
                    );
                  })()}
                </div>
              )}

              {/* Decades + networks/languages row */}
              {(data.fun.decades?.length || data.fun.topNetworks?.length || data.fun.topLanguages?.length) && (
                <div className="grid grid-cols-1 gap-3">
                  {data.fun.decades && data.fun.decades.length > 0 && (
                    <div className="rounded-xl border border-white/5 bg-card p-4">
                      <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-2">By decade</div>
                      <div className="flex flex-wrap gap-2">
                        {data.fun.decades.slice(0, 5).map((d) => (
                          <span key={d.decade} className="px-2.5 py-1 rounded-md bg-white/5 text-xs tabular-nums">
                            <span className="font-semibold">{d.decade}s</span>
                            <span className="text-gray-500 ml-1">{fmtHours(d.seconds)}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {data.fun.topNetworks && data.fun.topNetworks.length > 0 && (
                    <div className="rounded-xl border border-white/5 bg-card p-4">
                      <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-2">Networks you live on</div>
                      <div className="flex flex-wrap gap-2">
                        {data.fun.topNetworks.map((n) => (
                          <span key={n.name} className="px-2.5 py-1 rounded-md bg-white/5 text-xs tabular-nums">
                            <span className="font-semibold">{n.name}</span>
                            <span className="text-gray-500 ml-1">{fmtHours(n.seconds)}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {data.fun.topLanguages && data.fun.topLanguages.length > 1 && (
                    <div className="rounded-xl border border-white/5 bg-card p-4">
                      <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-2">Languages</div>
                      <div className="flex flex-wrap gap-2">
                        {data.fun.topLanguages.map((l) => (
                          <span key={l.name} className="px-2.5 py-1 rounded-md bg-white/5 text-xs tabular-nums">
                            <span className="font-semibold">{l.name}</span>
                            <span className="text-gray-500 ml-1">{fmtHours(l.seconds)}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Library coverage */}
          {data.libraries.length > 0 && (
            <div className="rounded-2xl border border-white/5 bg-card p-5 mb-4">
              <h3 className="font-semibold mb-1">Library coverage</h3>
              <p className="text-xs text-gray-500 mb-3">How much of each library you've actually touched.</p>
              <div className="space-y-3">
                {data.libraries.map((lib) => {
                  const noun = lib.total === 1 ? lib.noun : `${lib.noun}s`;
                  return (
                    <div key={lib.sectionId} className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                      <div className="flex items-baseline justify-between gap-3">
                        <div className="font-medium truncate">{lib.library}</div>
                        <div className="text-xs text-gray-400 tabular-nums shrink-0">
                          {lib.total.toLocaleString()} {noun}
                        </div>
                      </div>
                      <div className="mt-2 flex items-baseline justify-between gap-3">
                        <div className="text-2xl font-bold tabular-nums">{lib.pct}%</div>
                        <div className="text-xs text-gray-500 tabular-nums">
                          {lib.watched.toLocaleString()} {lib.verb}
                        </div>
                      </div>
                      <div className="mt-2 h-1.5 bg-white/5 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-purple-500 to-pink-500"
                          style={{ width: `${Math.min(100, lib.pct)}%` }}
                        />
                      </div>
                      <p className="text-xs text-gray-400 italic mt-2">{lib.blurb}</p>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Top shows */}
          <div className="rounded-2xl border border-white/5 bg-card p-5 mb-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="font-semibold">Top shows</h3>
                {showsFromPlex && (
                  <p className="text-[10px] text-purple-400/70 uppercase tracking-wider">Cross-server · Plex history</p>
                )}
              </div>
              <span className="text-xs text-gray-500">
                {showsFromPlex
                  ? `${fmtNum(totalShowEps)} eps across top ${data.topShows.length}`
                  : `${fmtHours(totalShowSeconds)} across top ${data.topShows.length}`}
              </span>
            </div>
            {data.topShows.length === 0 && (
              <p className="text-sm text-gray-500">Crickets. Maybe try a show?</p>
            )}
            <div className="space-y-2">
              {data.topShows.map((s, i) => {
                const metric = showsFromPlex ? (s.episodesWatched || 0) : (s.seconds || 0);
                const maxMetric = showsFromPlex
                  ? (data.topShows[0]?.episodesWatched || 1)
                  : (data.topShows[0]?.seconds || 1);
                const pct = (metric / maxMetric) * 100;
                return (
                  <div key={`${s.title}-${i}`} className="relative rounded-lg overflow-hidden">
                    <div
                      className="absolute inset-y-0 left-0 bg-purple-500/15"
                      style={{ width: `${pct}%` }}
                    />
                    <div className="relative flex items-center justify-between px-3 py-2 text-sm">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-gray-500 text-xs w-4 shrink-0">{i + 1}</span>
                        <span className="truncate font-medium">{s.title}</span>
                      </div>
                      <div className="text-xs text-gray-400 shrink-0 ml-3 tabular-nums">
                        {showsFromPlex
                          ? `${fmtNum(s.episodesWatched || 0)} eps · ${fmtNum(s.plays)} plays`
                          : `${fmtHours(s.seconds || 0)} · ${fmtNum(s.plays)}`}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Top movies */}
          <div className="rounded-2xl border border-white/5 bg-card p-5 mb-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="font-semibold">Top movies</h3>
                {moviesFromPlex && (
                  <p className="text-[10px] text-purple-400/70 uppercase tracking-wider">Cross-server · Plex history</p>
                )}
              </div>
              <span className="text-xs text-gray-500">
                {moviesFromPlex
                  ? `${fmtNum(totalMoviePlays)} plays across top ${data.topMovies.length}`
                  : `${fmtHours(totalMovieSeconds)} across top ${data.topMovies.length}`}
              </span>
            </div>
            {data.topMovies.length === 0 && (
              <p className="text-sm text-gray-500">No movies in this window. Series only? Respect the commitment.</p>
            )}
            <div className="space-y-2">
              {data.topMovies.map((m, i) => {
                const metric = moviesFromPlex ? (m.plays || 0) : (m.seconds || 0);
                const maxMetric = moviesFromPlex
                  ? (data.topMovies[0]?.plays || 1)
                  : (data.topMovies[0]?.seconds || 1);
                const pct = (metric / maxMetric) * 100;
                return (
                  <div key={`${m.title}-${i}`} className="relative rounded-lg overflow-hidden">
                    <div
                      className="absolute inset-y-0 left-0 bg-indigo-500/15"
                      style={{ width: `${pct}%` }}
                    />
                    <div className="relative flex items-center justify-between px-3 py-2 text-sm">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-gray-500 text-xs w-4 shrink-0">{i + 1}</span>
                        <span className="truncate font-medium">{m.title}{m.year ? ` (${m.year})` : ""}</span>
                      </div>
                      <div className="text-xs text-gray-400 shrink-0 ml-3 tabular-nums">
                        {moviesFromPlex
                          ? `${fmtNum(m.plays)} play${m.plays === 1 ? "" : "s"}`
                          : `${fmtHours(m.seconds || 0)} · ${fmtNum(m.plays)}`}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Top platforms */}
          <div className="rounded-2xl border border-white/5 bg-card p-5 mb-4">
            <h3 className="font-semibold mb-3">Where you watch</h3>
            {data.topPlatforms.length === 0 && (
              <p className="text-sm text-gray-500">No data yet.</p>
            )}
            <div className="space-y-2">
              {data.topPlatforms.map((p, i) => {
                const totalSec = data.topPlatforms.reduce((s, x) => s + x.seconds, 0) || 1;
                const pct = (p.seconds / totalSec) * 100;
                return (
                  <div key={`${p.platform}-${i}`} className="px-3 py-2 rounded-lg bg-white/[0.02]">
                    <div className="flex items-center justify-between text-sm">
                      <div className="font-medium">{p.platform}</div>
                      <div className="text-xs text-gray-400 tabular-nums">
                        {fmtHours(p.seconds)} · {Math.round(pct)}%
                      </div>
                    </div>
                    <div className="text-xs text-gray-500 italic mt-0.5">{platformQuip(p.platform)}</div>
                    <div className="mt-1.5 h-1 bg-white/5 rounded-full overflow-hidden">
                      <div className="h-full bg-emerald-500/40" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Period comparison */}
          <div className="rounded-2xl border border-white/5 bg-card p-5 mb-4">
            <h3 className="font-semibold mb-3">All periods</h3>
            <div className="grid grid-cols-2 gap-3">
              {PERIOD_OPTIONS.map((opt) => {
                const p = data.periods[opt.key as keyof DetailedResp["periods"]];
                return (
                  <div
                    key={opt.key}
                    className={`p-3 rounded-xl border ${
                      period === opt.key
                        ? "border-purple-500/40 bg-purple-500/10"
                        : "border-white/5 bg-white/[0.02]"
                    }`}
                  >
                    <div className="text-xs text-gray-500">{opt.label}</div>
                    <div className="font-semibold tabular-nums">{p.duration.compact}</div>
                    <div className="text-xs text-gray-500">{p.playsLabel}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
