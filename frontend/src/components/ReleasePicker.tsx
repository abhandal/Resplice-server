import { useState } from "react";

export interface Release {
  guid: string;
  indexerId: number;
  title: string;
  quality: string;
  qualityWeight: number;
  size: number;
  sizeGB: string;
  protocol: "usenet" | "torrent";
  indexer: string;
  seeders: number | null;
  age: number;
  rejected: boolean;
  rejections: string[];
  recommended: boolean;
}

interface Props {
  releases: Release[];
  blocklisted: string;
  onGrab: (release: Release) => void;
  loading: boolean;
}

function qualityLabel(q: string): string {
  if (/2160|4k/i.test(q)) return "4K";
  if (/1080/i.test(q)) return "1080p";
  if (/720/i.test(q)) return "720p";
  if (/480|576/i.test(q)) return "480p";
  return q;
}

function qualityColor(label: string): string {
  if (label === "4K") return "bg-amber-500/20 text-amber-400";
  if (label === "1080p") return "bg-emerald-500/20 text-emerald-400";
  if (label === "720p") return "bg-blue-500/20 text-blue-400";
  return "bg-gray-500/20 text-gray-400";
}

export default function ReleasePicker({ releases, blocklisted, onGrab, loading }: Props) {
  const [selected, setSelected] = useState<Release | null>(null);

  return (
    <div>
      {/* Blocklisted banner */}
      {blocklisted && (
        <div className="text-xs text-gray-500 mb-3 break-all">
          Blocked: {blocklisted}
        </div>
      )}

      {/* Release list */}
      <div className="max-h-[50vh] overflow-y-auto space-y-2">
        {releases.map((release) => {
          const label = qualityLabel(release.quality);
          const color = qualityColor(label);
          const isSelected = selected?.guid === release.guid;

          return (
            <div
              key={release.guid}
              onClick={() => setSelected(release)}
              className={`bg-white/5 rounded-xl p-3 border transition cursor-pointer ${
                isSelected
                  ? "border-purple-500 ring-1 ring-purple-500/50"
                  : "border-white/5 hover:border-purple-500/30"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                {/* Left side */}
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded-full shrink-0 ${color}`}>
                    {label}
                  </span>
                  <span className="text-sm font-bold shrink-0">{release.sizeGB} GB</span>
                  {release.protocol === "usenet" ? (
                    <span className="text-xs text-indigo-400 shrink-0">Usenet</span>
                  ) : (
                    <span className="text-xs text-orange-400 shrink-0">
                      Torrent{release.seeders != null ? ` \u00B7 S:${release.seeders}` : ""}
                    </span>
                  )}
                </div>

                {/* Right side */}
                {release.recommended && (
                  <span className="bg-purple-500/20 text-purple-300 text-xs px-2 py-0.5 rounded-full shrink-0">
                    Recommended
                  </span>
                )}
              </div>

              {/* Release title */}
              <div className="text-xs text-gray-500 mt-1 break-all">{release.title}</div>

            </div>
          );
        })}
      </div>

      {/* Grab button */}
      {selected && (
        <button
          onClick={() => onGrab(selected)}
          disabled={loading}
          className="w-full mt-4 py-3 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-500 font-semibold disabled:opacity-50 transition flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Grabbing...
            </>
          ) : (
            "Manual Fix"
          )}
        </button>
      )}
    </div>
  );
}
