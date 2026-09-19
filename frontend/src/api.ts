const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || resp.statusText);
  }
  return resp.json();
}

export const api = {
  authMe: () => request<any>("/auth/me"),
  authPlex: (authToken: string) =>
    request<any>("/auth/plex", {
      method: "POST",
      body: JSON.stringify({ authToken }),
    }),
  logout: () => request<any>("/auth/logout", { method: "POST" }),
  search: (q: string) => request<any[]>(`/search?q=${encodeURIComponent(q)}`),
  recentlyWatched: () => request<any[]>("/recently-watched"),
  seasons: (seriesId: number) => request<any>(`/series/${seriesId}/seasons`),
  episodes: (seriesId: number, season: number) =>
    request<any[]>(`/series/${seriesId}/episodes?season=${season}`),
  movie: (movieId: number) => request<any>(`/movie/${movieId}`),
  fix: (body: any) =>
    request<any>("/fix", { method: "POST", body: JSON.stringify(body) }),
  queue: () => request<any[]>("/queue"),
  removeQueueItem: (fixId: string) => request<any>(`/queue/${fixId}`, { method: "DELETE" }),
  clearQueue: () => request<any>("/queue", { method: "DELETE" }),
  notify: (fixId: string) =>
    request<any>("/notify", { method: "POST", body: JSON.stringify({ fixId }) }),
  rateLimit: () => request<any>("/rate-limit"),
  plexStatus: () => request<any>("/plex-status"),
  adminUsers: () => request<any[]>("/admin/users"),
  adminHistory: () => request<any[]>("/admin/history"),
  updateUserLimits: (userId: number, maxPerDay: number, cooldown: number) =>
    request<any>(`/admin/users/${userId}/limits`, {
      method: "PUT",
      body: JSON.stringify({ maxPerDay, cooldown }),
    }),
  revokeUser: (userId: number) =>
    request<any>(`/admin/users/${userId}/revoke`, { method: "POST" }),
  plexUsers: () => request<any[]>("/auth/plex-users"),
  importUsers: (userIds: number[]) =>
    request<any>("/auth/import-users", { method: "POST", body: JSON.stringify({ userIds }) }),
  scanFolder: (body: { type: "season" | "movie"; seriesId?: number; seasonNumber?: number; movieId?: number }) =>
    request<any>("/admin/scan", { method: "POST", body: JSON.stringify(body) }),
  checkRepeat: (type: string, id: number) =>
    request<{ repeat: boolean }>(
      `/fix/check-repeat?type=${type}&${type === "episode" ? "episodeId" : "movieId"}=${id}`
    ),
  searchReleases: (body: any) =>
    request<{ releases: any[]; blocklisted: string }>(
      "/fix/search-releases",
      { method: "POST", body: JSON.stringify(body), signal: AbortSignal.timeout(130000) }
    ),
  grabRelease: (body: any) =>
    request<{ fixId: string; status: string }>(
      "/fix/grab",
      { method: "POST", body: JSON.stringify(body) }
    ),
  statsSummary: () => request<any>("/stats/summary"),
  statsDetailed: (period: string) =>
    request<any>(`/stats/detailed?period=${encodeURIComponent(period)}`),
};
