import { useRef, useState, useCallback, useEffect } from "react";

interface Props {
  children: React.ReactNode;
}

const jokes = [
  "Pull my finger...",
  "Yank it like you mean it",
  "That's what she said",
  "Buffering your patience...",
  "Plex goes brrr",
  "Hold on, waking up the hamster",
  "Summoning the content gods",
  "Did you try turning it off and on?",
  "One does not simply refresh",
  "Plot twist: nothing changed",
  "Refreshing harder won't help",
  "You spin me right round...",
  "Loading... just kidding",
  "Your patience is buffering",
  "Shake it like a Polaroid",
  "Almost there... probably",
  "Have you tried unplugging it?",
  "Reticulating splines...",
  "Insert coin to continue",
  "Downloading more RAM...",
];

export default function PullToRefresh({ children }: Props) {
  const [pulling, setPulling] = useState(false);
  const [pullDistance, setPullDistance] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [joke] = useState(() => jokes[Math.floor(Math.random() * jokes.length)]);
  const startY = useRef(0);
  const threshold = 80;

  const isAtTop = () => window.scrollY <= 0;

  const handleTouchStart = useCallback((e: TouchEvent) => {
    if (isAtTop() && !refreshing) {
      startY.current = e.touches[0].clientY;
      setPulling(true);
    }
  }, [refreshing]);

  const handleTouchMove = useCallback((e: TouchEvent) => {
    if (!pulling || refreshing) return;
    const delta = e.touches[0].clientY - startY.current;
    if (delta > 0 && isAtTop()) {
      setPullDistance(Math.min(delta * 0.5, threshold * 1.5));
    } else {
      setPullDistance(0);
    }
  }, [pulling, refreshing]);

  const handleTouchEnd = useCallback(() => {
    if (pullDistance >= threshold) {
      setRefreshing(true);
      setPullDistance(threshold);
      setTimeout(() => window.location.reload(), 300);
    } else {
      setPullDistance(0);
    }
    setPulling(false);
  }, [pullDistance]);

  useEffect(() => {
    document.addEventListener("touchstart", handleTouchStart, { passive: true });
    document.addEventListener("touchmove", handleTouchMove, { passive: true });
    document.addEventListener("touchend", handleTouchEnd);
    return () => {
      document.removeEventListener("touchstart", handleTouchStart);
      document.removeEventListener("touchmove", handleTouchMove);
      document.removeEventListener("touchend", handleTouchEnd);
    };
  }, [handleTouchStart, handleTouchMove, handleTouchEnd]);

  const progress = Math.min(pullDistance / threshold, 1);
  const pastThreshold = progress >= 1;

  return (
    <>
      {(pullDistance > 0 || refreshing) && (
        <div
          className="fixed top-0 left-0 right-0 z-50 flex items-center justify-center"
          style={{ height: refreshing ? threshold : pullDistance }}
        >
          <div className="flex flex-col items-center gap-1.5">
            {refreshing ? (
              <div className="w-7 h-7 border-[2.5px] border-white/20 border-t-white rounded-full animate-spin" />
            ) : (
              <svg
                width="28"
                height="28"
                viewBox="0 0 24 24"
                fill="none"
                stroke="white"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{
                  opacity: progress,
                  transform: `rotate(${pastThreshold ? 180 : 0}deg)`,
                  transition: "transform 0.2s",
                }}
              >
                <line x1="12" y1="5" x2="12" y2="19" />
                <polyline points="19 12 12 19 5 12" />
              </svg>
            )}
            {progress > 0.3 && (
              <span
                className="text-[11px] text-white/50 whitespace-nowrap"
                style={{ opacity: Math.min((progress - 0.3) / 0.4, 1) }}
              >
                {refreshing ? "Refreshing..." : joke}
              </span>
            )}
          </div>
        </div>
      )}
      <div
        style={{
          transform: pullDistance > 0 || refreshing ? `translateY(${refreshing ? threshold : pullDistance}px)` : undefined,
          transition: pulling ? "none" : "transform 0.2s",
        }}
      >
        {children}
      </div>
    </>
  );
}
