import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";
import { api } from "../api";
import { useAuth } from "./AuthContext";

interface QueueItem {
  id: string;
  title: string;
  type: string;
  status: string;
  progress: number;
  stuckReason: string;
  notified: boolean;
  episodeId?: number;
  movieId?: number;
}

interface PendingFix {
  type: "episode" | "movie";
  id: number;
}

interface QueueContextType {
  items: QueueItem[];
  expanded: boolean;
  setExpanded: (v: boolean) => void;
  activeCount: number;
  notify: (fixId: string) => Promise<void>;
  isInProgress: (type: "episode" | "movie", id: number) => boolean;
  markPending: (type: "episode" | "movie", id: number) => void;
  clearPending: (type: "episode" | "movie", id: number) => void;
  removeItem: (fixId: string) => Promise<void>;
  clearAll: () => Promise<void>;
  refreshKey: number;
}

const QueueContext = createContext<QueueContextType>(null!);
export const useQueue = () => useContext(QueueContext);

export function QueueProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [items, setItems] = useState<QueueItem[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [pending, setPending] = useState<PendingFix[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [prevStatuses, setPrevStatuses] = useState<Record<string, string>>({});

  const poll = useCallback(async () => {
    if (!user) return;
    try {
      const data = await api.queue();
      setItems((prev) => {
        // Detect items that just completed → bump refreshKey
        for (const item of data) {
          const old = prev.find((p) => p.id === item.id);
          if (old && old.status !== "done" && old.status !== "available" &&
              (item.status === "done" || item.status === "available")) {
            setRefreshKey((k) => k + 1);
            break;
          }
        }
        return data;
      });
      // Clear pending items that now appear in the real queue
      setPending((prev) =>
        prev.filter((p) => !data.some((q) => {
          if (q.status === "done" || q.status === "available") return false;
          return p.type === "episode" ? q.episodeId === p.id : q.movieId === p.id;
        }))
      );
    } catch {}
  }, [user]);

  useEffect(() => {
    poll();
    const i = setInterval(poll, 10000);
    return () => clearInterval(i);
  }, [user]);

  const notify = async (fixId: string) => {
    await api.notify(fixId);
    await poll();
  };

  const markPending = (type: "episode" | "movie", id: number) => {
    setPending((prev) => [...prev, { type, id }]);
    setTimeout(poll, 2000);
  };

  const clearPending = (type: "episode" | "movie", id: number) => {
    setPending((prev) => prev.filter((p) => !(p.type === type && p.id === id)));
  };

  const removeItem = async (fixId: string) => {
    await api.removeQueueItem(fixId);
    setItems((prev) => prev.filter((i) => i.id !== fixId));
  };

  const clearAll = async () => {
    await api.clearQueue();
    setItems([]);
    setPending([]);
  };

  const activeCount = items.filter((i) => i.status !== "done" && i.status !== "available").length + pending.length;

  const isInProgress = (type: "episode" | "movie", id: number) => {
    // Check pending (optimistic)
    if (pending.some((p) => p.type === type && p.id === id)) return true;
    // Check real queue
    return items.some((i) => {
      if (i.status === "done" || i.status === "available") return false;
      if (type === "episode") return i.episodeId === id;
      return i.movieId === id;
    });
  };

  return (
    <QueueContext.Provider value={{ items, expanded, setExpanded, activeCount, notify, isInProgress, markPending, clearPending, removeItem, clearAll, refreshKey }}>
      {children}
    </QueueContext.Provider>
  );
}
