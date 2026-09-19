import { useState, useEffect, useRef } from "react";
import { useQueue } from "../context/QueueContext";
import Toast from "./Toast";

interface ToastMsg {
  id: string;
  message: string;
  type: "success" | "warning";
}

const searchingLines = [
  "Hold up, things are happening...",
  "Searching the galaxy far, far away...",
  "I'm gonna make him an offer he can't refuse...",
  "After all, tomorrow is another download",
  "Houston, we have a search query",
  "To download, or not to download...",
  "Frankly my dear, I don't give a buffer",
  "Here's looking at you, file...",
  "You talking to me? I'm searching here",
  "May the bandwidth be with you",
  "I'll be back... with results",
  "You can't handle the search!",
  "Roads? Where we're going we don't need roads",
  "Just keep searching, just keep searching...",
  "My precious... file",
  "Run, Forrest, run! ...the search",
  "Say hello to my little torrent",
  "I see downloaded people",
  "Shaking the internet tree...",
  "Asking nicely...",
];

const plexSyncLines = [
  "Checking if Plex got the memo...",
  "Plex is thinking about it...",
  "Poking Plex with a stick...",
  "Almost there, don't touch anything",
  "It's happening... probably",
  "Plex is doing its thing...",
  "Any second now...",
  "Waiting for Plex to notice...",
  "The file is IN the computer",
  "Plex acknowledged our existence",
];

const availableLines = [
  "It's ready! Go refresh Infuse!",
  "Done! Now go watch it already",
  "Your entertainment awaits, refresh Infuse",
  "It's there! ...but Infuse doesn't know yet",
  "Ready to roll — give Infuse a refresh",
];

export default function QueueBar() {
  const { items, expanded, setExpanded, notify, removeItem, clearAll } = useQueue();
  const [toasts, setToasts] = useState<ToastMsg[]>([]);
  const [prevStatuses, setPrevStatuses] = useState<Record<string, string>>({});

  useEffect(() => {
    for (const item of items) {
      const prev = prevStatuses[item.id];
      if (prev && prev !== item.status) {
        if (item.status === "available") {
          setToasts((t) => [...t, { id: item.id + "-available", message: `⚠️ ${item.title} is ready — Refresh Infuse!`, type: "warning" }]);
        } else if (item.status === "stuck") {
          setToasts((t) => [...t, { id: item.id + "-stuck", message: `${item.title} is stuck`, type: "warning" }]);
        }
      }
    }
    setPrevStatuses(Object.fromEntries(items.map((i) => [i.id, i.status])));
  }, [items]);

  const handleNotify = async (fixId: string) => {
    try {
      await notify(fixId);
    } catch (e: any) {
      alert(e.message);
    }
  };

  const statusColor: Record<string, string> = {
    searching: "text-purple-400",
    downloading: "text-purple-400",
    importing: "text-purple-400",
    done: "text-emerald-400",
    available: "text-amber-400",
    stuck: "text-yellow-400",
  };

  const [tick, setTick] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 3000);
    return () => clearInterval(interval);
  }, []);

  const cycleText = (lines: string[], itemId: string) => {
    // Use item ID hash + tick for per-item offset so they don't all show the same line
    const hash = itemId.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
    return lines[(hash + tick) % lines.length];
  };

  const statusText = (item: any) => {
    if (item.status === "downloading") return `Downloading... ${item.progress.toFixed(0)}%`;
    if (item.status === "stuck") return "Stuck — Manual import required";
    if (item.status === "done") return cycleText(plexSyncLines, item.id);
    if (item.status === "available") return cycleText(availableLines, item.id);
    if (item.status === "searching") return cycleText(searchingLines, item.id);
    if (item.status === "importing") return "Importing...";
    return "Working on it...";
  };

  return (
    <>
      {toasts.map((t) => (
        <Toast
          key={t.id}
          message={t.message}
          type={t.type}
          onDismiss={() => setToasts((ts) => ts.filter((x) => x.id !== t.id))}
        />
      ))}

      {expanded && (
        <div className="fixed inset-0 z-50 bg-black/60" onClick={() => setExpanded(false)}>
          <div
            className="absolute bottom-0 left-0 right-0 bg-bg border-t border-white/10 rounded-t-2xl max-h-[70vh] overflow-y-auto p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between items-center mb-4">
              <h3 className="font-semibold">Your Fix Requests</h3>
              <div className="flex items-center gap-3">
                {items.length > 0 && (
                  <button
                    onClick={() => { clearAll(); setExpanded(false); }}
                    className="text-red-400 text-xs hover:text-red-300 transition"
                  >
                    Clear all
                  </button>
                )}
                <button onClick={() => setExpanded(false)} className="text-gray-500 text-sm">Close</button>
              </div>
            </div>
            {items.length === 0 ? (
              <p className="text-gray-500 text-sm text-center py-8">No fix requests yet</p>
            ) : (
              <div className="space-y-3">
                {items.map((item) => (
                  <div
                    key={item.id}
                    className={`bg-card rounded-xl p-4 border ${
                      item.status === "available" ? "border-amber-500/30" :
                      item.status === "done" ? "border-emerald-500/20" :
                      item.status === "stuck" ? "border-yellow-500/20" :
                      "border-indigo-500/20"
                    }`}
                  >
                    <div className="flex justify-between items-center">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium">{item.title}</div>
                        <div className={`text-xs mt-1 ${statusColor[item.status]}`}>{statusText(item)}</div>
                      </div>
                      <button
                        onClick={() => removeItem(item.id)}
                        className="ml-2 w-6 h-6 rounded-full hover:bg-white/10 flex items-center justify-center text-gray-500 hover:text-white transition shrink-0"
                        title="Remove"
                      >
                        ×
                      </button>
                    </div>
                    {item.status === "downloading" && (
                      <div className="mt-2 h-1 bg-white/5 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all"
                          style={{ width: `${item.progress}%` }}
                        />
                      </div>
                    )}
                    {item.status === "stuck" && !item.notified && (
                      <button
                        onClick={() => handleNotify(item.id)}
                        className="mt-3 w-full py-2.5 rounded-lg bg-gradient-to-r from-violet-600 to-purple-500 text-sm font-semibold transition hover:from-violet-700 hover:to-purple-600"
                      >
                        Notify admin
                      </button>
                    )}
                    {item.status === "stuck" && item.notified && (
                      <div className="mt-2 text-xs text-gray-500">The admin has been notified</div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
