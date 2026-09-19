import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
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

const fmtHoursShort = (s: number) => {
  const h = s / 3600;
  if (h < 1) return `${Math.round(s / 60)}m`;
  if (h < 10) return `${h.toFixed(1)}h`;
  return `${Math.round(h).toLocaleString()}h`;
};

interface SummaryResp {
  periods: { "30days": Period; "90days": Period; ytd: Period; allTime: Period };
  username: string;
}

const PERIODS: { key: keyof SummaryResp["periods"]; label: string }[] = [
  { key: "30days", label: "30 Days" },
  { key: "90days", label: "90 Days" },
  { key: "ytd", label: "YTD" },
  { key: "allTime", label: "All Time" },
];

export default function StatsCard() {
  const [data, setData] = useState<SummaryResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [active, setActive] = useState<keyof SummaryResp["periods"]>("30days");
  const navigate = useNavigate();

  useEffect(() => {
    api.statsSummary()
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="mb-6 rounded-2xl border border-white/5 bg-card p-4 animate-pulse h-32" />
    );
  }
  if (!data) return null;

  const period = data.periods[active];

  return (
    <div className="mb-6 rounded-2xl border border-white/5 bg-gradient-to-br from-purple-500/5 via-card to-card overflow-hidden">
      <div className="px-4 pt-4 pb-3">
        <div className="flex items-baseline justify-between">
          <p className="text-xs font-medium text-gray-400 uppercase tracking-wider">Your watch time</p>
          <button
            onClick={() => navigate(`/stats?period=${active}`)}
            className="text-xs text-purple-400 hover:text-purple-300 font-medium transition"
          >
            See more →
          </button>
        </div>
        <div className="flex items-end gap-2 mt-2">
          <div className="text-3xl font-bold tabular-nums">{period.duration.compact}</div>
          <div className="text-xs text-gray-500 mb-1">{period.playsLabel}</div>
        </div>
        {period.byType?.length > 0 && (
          <div className="mt-1.5 text-xs text-gray-400 tabular-nums">
            {period.byType
              .map((b) => `${fmtHoursShort(b.seconds)} ${b.library.toLowerCase()}`)
              .join(" · ")}
          </div>
        )}
        <div className="mt-1.5 flex items-center gap-2 text-xs">
          <span className="px-2 py-0.5 rounded-md bg-purple-500/15 text-purple-300 font-medium">
            {period.tier.label}
          </span>
          <span className="text-gray-500 truncate">{period.duration.fun}</span>
        </div>
        <p className="text-xs text-gray-400 mt-1.5 italic">{period.tier.blurb}</p>
      </div>
      <div className="grid grid-cols-4 border-t border-white/5">
        {PERIODS.map((p) => {
          const isActive = active === p.key;
          return (
            <button
              key={p.key}
              onClick={() => setActive(p.key)}
              className={`px-2 py-2.5 text-xs font-medium transition ${
                isActive
                  ? "bg-purple-500/10 text-white"
                  : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
              }`}
            >
              {p.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
