import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { api } from "../api";

interface UserInfo {
  id: number;
  username: string;
  thumb: string;
  isAdmin: boolean;
  rateLimit: {
    remaining: number;
    maxPerDay: number;
    cooldown: number;
    cooldownLeft: number;
  };
}

interface PlexUser {
  id: number;
  username: string;
  thumb: string;
  imported: boolean;
}

interface HistoryItem {
  userId: number;
  username: string;
  type: string;
  title: string;
  timestamp: number;
}

type Tab = "users" | "history";

export default function Admin() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("users");
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [historyItems, setHistory] = useState<HistoryItem[]>([]);
  const [plexUsers, setPlexUsers] = useState<PlexUser[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [showImport, setShowImport] = useState(false);
  const [importing, setImporting] = useState(false);
  const [editingUser, setEditingUser] = useState<UserInfo | null>(null);
  const [editMax, setEditMax] = useState(5);
  const [editCooldown, setEditCooldown] = useState(5);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const loadUsers = () => {
    api.adminUsers().then(setUsers).catch(console.error).finally(() => setLoading(false));
  };

  const loadHistory = () => {
    api.adminHistory().then(setHistory).catch(console.error);
  };

  useEffect(() => {
    if (!user?.isAdmin) { navigate("/"); return; }
    loadUsers();
    loadHistory();
  }, [user]);

  const openImport = async () => {
    setShowImport(true);
    try { setPlexUsers(await api.plexUsers()); } catch {}
  };

  const toggleSelect = (id: number) => {
    setSelected((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  };

  const handleImport = async () => {
    if (selected.size === 0) return;
    setImporting(true);
    try {
      await api.importUsers(Array.from(selected));
      setShowImport(false);
      setSelected(new Set());
      loadUsers();
      setPlexUsers(await api.plexUsers());
    } catch (e: any) { alert(e.message); }
    finally { setImporting(false); }
  };

  const openEditLimits = (u: UserInfo) => {
    setEditingUser(u);
    setEditMax(u.rateLimit.maxPerDay);
    setEditCooldown(u.rateLimit.cooldown / 60); // show in minutes
  };

  const saveLimits = async () => {
    if (!editingUser) return;
    await api.updateUserLimits(editingUser.id, editMax, editCooldown * 60);
    setEditingUser(null);
    loadUsers();
  };

  const formatTime = (ts: number) => {
    const d = new Date(ts * 1000);
    return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  if (loading) return <div className="p-5 text-gray-500">Loading...</div>;

  return (
    <div className="p-5">
      <button onClick={() => navigate(-1)} className="text-gray-400 text-sm mb-3 hover:text-white transition">
        ← Back
      </button>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Settings</h2>
        <button
          onClick={openImport}
          className="px-4 py-2 rounded-lg bg-gradient-to-r from-indigo-500 to-purple-500 text-sm font-semibold transition hover:from-indigo-600 hover:to-purple-600"
        >
          Import Plex Users
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-5 bg-white/5 rounded-xl p-1">
        {(["users", "history"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => { setTab(t); if (t === "history") loadHistory(); }}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition ${
              tab === t ? "bg-gradient-to-r from-indigo-500 to-purple-500 text-white" : "text-gray-400 hover:text-white"
            }`}
          >
            {t === "users" ? "Users" : "History"}
          </button>
        ))}
      </div>

      {/* Users tab */}
      {tab === "users" && (
        <div className="space-y-3">
          {users.map((u) => {
            const initial = u.username.charAt(0).toUpperCase();
            const isUnlimited = u.rateLimit.remaining === -1;
            const used = isUnlimited ? 0 : u.rateLimit.maxPerDay - u.rateLimit.remaining;
            return (
              <div key={u.id} className="bg-card rounded-xl p-4 border border-white/5">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center text-sm font-semibold shrink-0">
                    {initial}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium flex items-center gap-2">
                      {u.username}
                      {u.isAdmin && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400 font-medium">ADMIN</span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                      {isUnlimited ? "Unlimited" : (
                        <>
                          {used}/{u.rateLimit.maxPerDay} fixes used today · {u.rateLimit.cooldown / 60}m cooldown
                          {u.rateLimit.cooldownLeft > 0 && (
                            <span className="text-yellow-400 ml-1">({Math.ceil(u.rateLimit.cooldownLeft / 60)}m left)</span>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                  {!u.isAdmin && (
                    <div className="flex gap-1 shrink-0">
                      <button
                        onClick={() => openEditLimits(u)}
                        className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-white/5 transition"
                      >
                        Edit
                      </button>
                      <button
                        onClick={async () => {
                          if (confirm(`Revoke ${u.username}'s access? They'll be logged out immediately.`)) {
                            await api.revokeUser(u.id);
                            loadUsers();
                          }
                        }}
                        className="text-xs text-red-400 hover:text-red-300 px-2 py-1 rounded hover:bg-red-500/10 transition"
                      >
                        Revoke
                      </button>
                    </div>
                  )}
                </div>
                {!isUnlimited && (
                  <div className="mt-3 h-1.5 bg-white/5 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all"
                      style={{ width: `${(used / u.rateLimit.maxPerDay) * 100}%` }}
                    />
                  </div>
                )}
              </div>
            );
          })}
          {users.length === 0 && (
            <p className="text-gray-500 text-sm text-center py-8">No users yet. Import Plex users to get started.</p>
          )}
        </div>
      )}

      {/* History tab */}
      {tab === "history" && (
        <div className="space-y-2">
          {historyItems.length === 0 ? (
            <p className="text-gray-500 text-sm text-center py-8">No fix requests yet</p>
          ) : historyItems.map((h, i) => (
            <div key={i} className="bg-card rounded-xl p-3 border border-white/5 flex justify-between items-center">
              <div>
                <div className="text-sm font-medium">{h.title}</div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {h.username} · {h.type} · {formatTime(h.timestamp)}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Edit limits modal */}
      {editingUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-5 bg-black/60" onClick={() => setEditingUser(null)}>
          <div className="bg-card rounded-2xl p-6 max-w-sm w-full border border-white/10" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-1">Edit Limits</h3>
            <p className="text-sm text-gray-400 mb-5">{editingUser.username}</p>

            <div className="space-y-4">
              <div>
                <label className="text-xs text-gray-400 block mb-1">Max fixes per day</label>
                <input
                  type="number"
                  value={editMax}
                  onChange={(e) => setEditMax(Number(e.target.value))}
                  min={1}
                  max={100}
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-gray-400 block mb-1">Cooldown (minutes)</label>
                <input
                  type="number"
                  value={editCooldown}
                  onChange={(e) => setEditCooldown(Number(e.target.value))}
                  min={0}
                  max={60}
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm"
                />
              </div>
            </div>

            <div className="flex gap-3 mt-5">
              <button onClick={() => setEditingUser(null)} className="flex-1 py-2.5 rounded-xl border border-white/10 text-gray-300 text-sm">Cancel</button>
              <button onClick={saveLimits} className="flex-1 py-2.5 rounded-xl bg-gradient-to-r from-indigo-500 to-purple-500 text-sm font-semibold">Save</button>
            </div>
          </div>
        </div>
      )}

      {/* Import modal */}
      {showImport && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-5 bg-black/60" onClick={() => setShowImport(false)}>
          <div className="bg-card rounded-2xl max-w-md w-full border border-white/10 max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="p-5 border-b border-white/5">
              <h3 className="text-lg font-semibold">Import Plex Users</h3>
              <p className="text-sm text-gray-400 mt-1">Select users to give access to Plex Support</p>
            </div>
            <div className="flex-1 overflow-y-auto p-5">
              {plexUsers.length === 0 ? (
                <p className="text-gray-500 text-sm text-center py-4">Loading...</p>
              ) : (
                <div className="space-y-2">
                  {plexUsers.map((pu) => {
                    const init = pu.username.charAt(0).toUpperCase();
                    const isSel = selected.has(pu.id);
                    return (
                      <div
                        key={pu.id}
                        onClick={() => !pu.imported && toggleSelect(pu.id)}
                        className={`rounded-xl p-3 flex items-center gap-3 border transition ${
                          pu.imported ? "border-white/5 opacity-50" : isSel ? "border-purple-500/50 bg-purple-500/10 cursor-pointer" : "border-white/5 hover:border-white/10 cursor-pointer"
                        }`}
                      >
                        <div className="w-9 h-9 rounded-full bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center text-sm font-semibold shrink-0">{init}</div>
                        <div className="flex-1"><div className="text-sm font-medium">{pu.username}</div></div>
                        {pu.imported ? (
                          <span className="text-xs text-gray-500">Already imported</span>
                        ) : (
                          <div className={`w-5 h-5 rounded border-2 flex items-center justify-center transition ${isSel ? "border-purple-500 bg-purple-500" : "border-gray-600"}`}>
                            {isSel && <span className="text-xs">✓</span>}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
            <div className="p-5 border-t border-white/5 flex gap-3">
              <button onClick={() => { const ids = plexUsers.filter((u) => !u.imported).map((u) => u.id); setSelected(new Set(ids)); }} className="px-4 py-2.5 rounded-xl border border-white/10 text-sm text-gray-300 hover:bg-white/5 transition">Select All</button>
              <div className="flex-1" />
              <button onClick={() => setShowImport(false)} className="px-4 py-2.5 rounded-xl border border-white/10 text-sm text-gray-300 hover:bg-white/5 transition">Cancel</button>
              <button onClick={handleImport} disabled={selected.size === 0 || importing} className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-indigo-500 to-purple-500 text-sm font-semibold disabled:opacity-50 transition">
                {importing ? "Importing..." : `Import (${selected.size})`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
