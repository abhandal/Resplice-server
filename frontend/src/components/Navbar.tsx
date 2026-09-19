import { useAuth } from "../context/AuthContext";
import { useQueue } from "../context/QueueContext";
import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";

export default function Navbar() {
  const { user, logout } = useAuth();
  const { activeCount, setExpanded } = useQueue();
  const [rateInfo, setRateInfo] = useState({ remaining: 10, maxPerDay: 10 });
  const [plexOnline, setPlexOnline] = useState<boolean | null>(null);
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api.rateLimit().then(setRateInfo).catch(() => {});
    api.plexStatus().then((d) => setPlexOnline(d.online)).catch(() => setPlexOnline(false));
    const i = setInterval(() => {
      api.rateLimit().then(setRateInfo).catch(() => {});
      api.plexStatus().then((d) => setPlexOnline(d.online)).catch(() => setPlexOnline(false));
    }, 30000);
    return () => clearInterval(i);
  }, []);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const initial = user?.username?.charAt(0)?.toUpperCase() || "?";

  return (
    <nav className="px-5 py-4 flex justify-between items-center border-b border-white/5">
      <div className="flex items-center gap-2 cursor-pointer" onClick={() => navigate("/")}>
        <div className="text-lg font-bold bg-gradient-to-r from-indigo-500 to-purple-500 bg-clip-text text-transparent">
          Plex Support
        </div>
        {plexOnline !== null && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
            plexOnline
              ? "bg-emerald-500/15 text-emerald-400"
              : "bg-red-500/15 text-red-400 animate-pulse"
          }`}>
            {plexOnline ? "Online" : "Offline"}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        {rateInfo.remaining !== -1 && (
          <span className="text-xs text-gray-500">
            {rateInfo.remaining}/{rateInfo.maxPerDay}
          </span>
        )}

        {/* Queue button */}
        <button
          onClick={() => setExpanded(true)}
          className="relative w-8 h-8 rounded-full bg-white/5 flex items-center justify-center text-sm hover:bg-white/10 transition"
        >
          <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
          </svg>
          {activeCount > 0 && (
            <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-purple-500 text-[10px] font-bold flex items-center justify-center">
              {activeCount}
            </span>
          )}
        </button>

        {/* Admin settings */}
        {user?.isAdmin && (
          <button
            onClick={() => navigate("/admin")}
            className="w-8 h-8 rounded-full bg-white/5 flex items-center justify-center text-sm hover:bg-white/10 transition"
          >
            <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>
        )}

        {/* User avatar */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setOpen(!open)}
            className="w-8 h-8 rounded-full bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center text-sm font-semibold cursor-pointer"
          >
            {initial}
          </button>
          {open && (
            <div className="absolute right-0 top-10 bg-card border border-white/10 rounded-lg p-1 z-50 shadow-lg shadow-black/40">
              <div className="px-3 py-2 text-xs text-gray-500 border-b border-white/5">{user?.username}</div>
              <button
                onClick={() => { setOpen(false); logout(); }}
                className="w-full text-left text-sm text-gray-400 hover:text-white hover:bg-white/5 px-3 py-2 rounded-md whitespace-nowrap transition"
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}
