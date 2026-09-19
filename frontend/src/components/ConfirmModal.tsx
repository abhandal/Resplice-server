import { useState, useEffect } from "react";
import { api } from "../api";
import { useQueue } from "../context/QueueContext";
import { useAuth } from "../context/AuthContext";
import ReleasePicker, { Release } from "./ReleasePicker";

const searchingReleasesLines = [
  "Scanning the universe for alternatives...",
  "Asking every indexer we know...",
  "This takes a moment, hang tight...",
  "Scouring the depths of the internet...",
  "Finding you something better...",
  "Good things come to those who wait...",
  "Almost there, probably...",
  "Negotiating with the download gods...",
];

interface Props {
  type: "episode" | "movie";
  title: string;
  subtitle: string;
  fileName: string;
  fileSize: number;
  quality: string;
  poster?: string;
  fixPayload: any;
  watched?: boolean;
  onClose: () => void;
}

export default function ConfirmModal({ type, title, subtitle, fileName, fileSize, quality, poster, fixPayload, watched, onClose }: Props) {
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");
  const [scanSuccess, setScanSuccess] = useState(false);
  const { setExpanded, markPending, clearPending } = useQueue();
  const { user } = useAuth();

  const [step, setStep] = useState<"confirm" | "searching" | "pick" | "grabbing">("confirm");
  const [releases, setReleases] = useState<Release[]>([]);
  const [blocklisted, setBlocklisted] = useState("");
  const [grabbing, setGrabbing] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [tick, setTick] = useState(0);

  const handleFix = async () => {
    setLoading(true);
    setError("");
    const id = fixPayload.episodeId || fixPayload.movieId;
    const fixType = fixPayload.type as "episode" | "movie";
    markPending(fixType, id);
    try {
      await api.fix(fixPayload);
      onClose();
      setExpanded(true);
    } catch (e: any) {
      clearPending(fixType, id);
      setError(e.message || "Something went wrong");
      setLoading(false);
    }
  };

  const handleScan = async () => {
    setScanning(true);
    setError("");
    setScanSuccess(false);
    try {
      if (type === "episode") {
        await api.scanFolder({
          type: "season",
          seriesId: fixPayload.seriesId,
          seasonNumber: fixPayload.seasonNumber,
        });
      } else {
        await api.scanFolder({
          type: "movie",
          movieId: fixPayload.movieId,
        });
      }
      setScanSuccess(true);
    } catch (e: any) {
      setError(e.message || "Scan failed");
    } finally {
      setScanning(false);
    }
  };

  const handleInteractive = async () => {
    setStep("searching");
    setError("");
    setSearchError("");
    try {
      const result = await api.searchReleases({
        type: fixPayload.type,
        episodeId: fixPayload.episodeId,
        fileId: fixPayload.fileId,
        seriesId: fixPayload.seriesId,
        movieId: fixPayload.movieId,
      });
      setReleases(result.releases);
      setBlocklisted(result.blocklisted);
      setStep("pick");
    } catch (e: any) {
      setSearchError(e.message || "Failed to search for releases");
      setStep("confirm");
    }
  };

  const handleGrab = async (release: Release) => {
    setGrabbing(true);
    setStep("grabbing");
    const id = fixPayload.episodeId || fixPayload.movieId;
    const fixType = fixPayload.type as "episode" | "movie";
    markPending(fixType, id);
    try {
      await api.grabRelease({
        type: fixPayload.type,
        episodeId: fixPayload.episodeId,
        seriesId: fixPayload.seriesId,
        movieId: fixPayload.movieId,
        fileId: fixPayload.fileId,
        title: fixPayload.title,
        guid: release.guid,
        indexerId: release.indexerId,
      });
      onClose();
      setExpanded(true);
    } catch (e: any) {
      clearPending(fixType, id);
      setError(e.message || "Failed to grab release");
      setStep("pick");
      setGrabbing(false);
    }
  };

  // Tick for cycling text
  useEffect(() => {
    if (step !== "searching") return;
    const interval = setInterval(() => setTick((t) => t + 1), 3000);
    return () => clearInterval(interval);
  }, [step]);

  const sizeGB = (fileSize / 1073741824).toFixed(1);
  const scanLabel = type === "episode" ? "Scan Season" : "Scan Movie";
  const busy = loading || scanning || step === "searching" || step === "grabbing";

  const handleBackdropClick = () => {
    if (step === "searching" || step === "grabbing") return;
    if (!loading && !scanning) onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-5 bg-black/60" onClick={handleBackdropClick}>
      <div
        className={`bg-card rounded-2xl p-6 w-full border border-white/10 transition-all ${step === "pick" ? "max-w-lg" : "max-w-sm"}`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header - shown in confirm and searching steps */}
        {(step === "confirm" || step === "searching") && (
          <>
            <div className="text-center mb-5">
              <div className="text-3xl mb-2">⚠️</div>
              <div className="text-lg font-semibold">Fix this?</div>
              <div className="text-sm text-gray-400 mt-1">This will delete the file and search for a new one</div>
            </div>

            <div className="bg-white/5 rounded-xl p-4 mb-5 flex gap-3">
              {poster && (
                <img src={poster} alt="" className="w-14 h-20 object-cover rounded-lg shrink-0" />
              )}
              <div className="min-w-0">
                <div className="font-semibold flex items-center gap-1.5">
                  {watched && (
                    <span title="Watched" className="text-emerald-400 shrink-0" aria-label="Watched">
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                        <path fillRule="evenodd" d="M16.704 5.29a1 1 0 010 1.42l-8 8a1 1 0 01-1.41 0l-4-4a1 1 0 111.41-1.42L8 12.59l7.293-7.3a1 1 0 011.41 0z" clipRule="evenodd" />
                      </svg>
                    </span>
                  )}
                  <span className="truncate">{title}</span>
                </div>
                <div className="text-sm text-gray-400 mt-1">{subtitle}</div>
                {fileName && (
                  <div className="text-xs text-gray-500 mt-2">
                    {fileName} · {sizeGB} GB · {quality}
                  </div>
                )}
              </div>
            </div>
          </>
        )}

        {/* Pick step header */}
        {step === "pick" && (
          <div className="mb-4">
            <div className="font-semibold">{title}</div>
            <div className="text-sm text-gray-400">{subtitle}</div>
          </div>
        )}

        {/* Error displays */}
        {searchError && <div className="text-red-400 text-sm mb-3 text-center">{searchError}</div>}
        {error && <div className="text-red-400 text-sm mb-3 text-center">{error}</div>}
        {scanSuccess && step === "confirm" && <div className="text-green-400 text-sm mb-3 text-center">Plex scan triggered</div>}

        {/* Step: confirm */}
        {step === "confirm" && (
          <>
            <div className="flex gap-3">
              <button
                onClick={onClose}
                disabled={busy}
                className="flex-1 py-3 rounded-xl border border-white/10 text-gray-300 font-medium hover:bg-white/5 transition disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleFix}
                disabled={busy}
                className="flex-1 py-3 rounded-xl bg-gradient-to-r from-red-600 to-red-500 font-semibold disabled:opacity-50 transition flex items-center justify-center gap-2"
              >
                {loading ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    Fixing...
                  </>
                ) : (
                  "Auto Fix"
                )}
              </button>
            </div>
            {/* Open to all users. The backend enforces the real limits on both
                halves of this flow: /fix/search-releases and /fix/grab check
                library-section access, and /fix/grab consumes the user's rate
                limit (admins bypass both). */}
            <button
              onClick={handleInteractive}
              disabled={busy}
              className="w-full mt-3 py-3 rounded-xl font-semibold disabled:opacity-50 transition border border-purple-500/30 text-purple-300 hover:bg-purple-500/10"
            >
              Manual Fix
            </button>

            {user?.isAdmin && (
              <button
                onClick={handleScan}
                disabled={busy || scanSuccess}
                className="w-full mt-3 py-2.5 rounded-xl border border-white/10 text-gray-300 text-sm font-medium hover:bg-white/5 transition disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {scanning ? (
                  <>
                    <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    Scanning...
                  </>
                ) : scanSuccess ? (
                  "✓ Scan Triggered"
                ) : (
                  `🔍 ${scanLabel}`
                )}
              </button>
            )}
          </>
        )}

        {/* Step: searching */}
        {step === "searching" && (
          <div className="text-center py-8">
            <div className="w-8 h-8 border-3 border-purple-400 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <div className="text-sm text-gray-400">
              {searchingReleasesLines[tick % searchingReleasesLines.length]}
            </div>
            <button onClick={onClose} className="text-gray-500 text-sm mt-4 hover:text-white transition">
              Cancel
            </button>
          </div>
        )}

        {/* Step: pick */}
        {step === "pick" && (
          <ReleasePicker
            releases={releases}
            blocklisted={blocklisted}
            onGrab={handleGrab}
            loading={grabbing}
          />
        )}

        {/* Step: grabbing */}
        {step === "grabbing" && (
          <div className="text-center py-8">
            <div className="w-8 h-8 border-3 border-purple-400 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <div className="text-sm text-gray-400">Grabbing your pick...</div>
          </div>
        )}
      </div>
    </div>
  );
}
