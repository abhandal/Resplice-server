# Resplice Server

A self-service repair portal for your Plex server. When someone hits a broken
file — playback dies halfway, audio out of sync, a botched download — they
search for it here, tap Fix, and Resplice deletes the bad file and has Sonarr
or Radarr grab a fresh copy. No more "hey, episode 4 is broken" messages that
you get to deal with three days later.

Users sign in with their own Plex account. Anyone your server is shared with
can log in; nobody else can. Each user only sees and fixes content from
libraries they actually have access to, and non-admin fixes are rate-limited
(10 a day, one per minute) so a bored teenager can't churn your indexers.

## What it does

- Search across your Sonarr and Radarr libraries, filtered per user
- One-tap fix: delete the file, mark it failed, trigger a new search
- Manual mode that lists candidate releases so you can pick a specific one
- Grab missing episodes or upgrade to a better release
- A live queue so users can watch their fix download
- Watch statistics per user, sourced from Plex history (Tautulli optional)
- "Notify admin" button for stuck downloads, via a Discord webhook
- Optional push notifications when a repair finishes (needs a companion iOS
  app built against the API — not included here)

## Requirements

- Plex, Sonarr and Radarr, already working
- Docker with the compose plugin
- **All services must see media at the same paths.** Resplice matches
  Sonarr/Radarr root folders against Plex library locations by string
  comparison. If Plex sees `/media/tv` and Sonarr sees `/data/tv` for the
  same share, per-user library filtering and post-fix scanning will quietly
  do the wrong thing. Align your mounts before starting.

## Setup

```bash
git clone <this repo>
cd Resplice-server
cp .env.sample .env
```

Fill in `.env`. The required values:

| Variable | What it is |
|---|---|
| `PLEX_TOKEN` | An admin token for your Plex server. [Finding yours](https://support.plex.tv/articles/204059436). **Whoever owns this token is the admin account** — sign in with that Plex account and you get the admin pages. |
| `PLEX_SERVER_URL` | Your server as reachable *from inside the container*. Not `localhost` — that's the container itself. Use the host's LAN IP or a Docker network hostname. |
| `SONARR_URL`, `SONARR_API_KEY` | Sonarr address and its API key (Settings → General). |
| `RADARR_URL`, `RADARR_API_KEY` | Same for Radarr. |
| `SESSION_SECRET` | Encrypts Plex tokens at rest. Generate with `openssl rand -hex 32`. The app refuses to start without it. |

Everything else in the sample is optional and documented inline: a Discord
webhook for stuck-download pings, Tautulli for richer stats, a request-system
URL (Overseerr, Jellyseerr, Ombi) to link to when someone searches for a
movie you don't have, and `HIDDEN_LIBRARIES` to keep libraries out of the
stats pages.

Then:

```bash
docker compose up -d --build
```

The app comes up on port 3080 (change with `PORT` in `.env`). First sign-in
with the admin's Plex account; other users appear as they log in, or you can
pre-import them from the admin page.

Runtime state — sessions, users, fix history — lives in `./data`, which is
bind-mounted into the container. Back that directory up if you care about it;
delete it to factory-reset.

## Exposing it to your users

The container speaks plain HTTP on port 8000 internally. If your users are
outside your LAN, put a reverse proxy with TLS in front (Caddy, Traefik,
nginx — anything), and set `SECURE_COOKIE=true` so session cookies are marked
Secure. Auth is handled by Plex itself via PIN sign-in, so there are no
passwords to manage, and accounts unshared from your Plex server lose access
here within a few minutes.

## Good to know

- The fix queue lives in memory. If the container restarts mid-repair, the
  download itself continues in Sonarr/Radarr and imports normally — but the
  progress entry vanishes from the queue and no completion notification is
  sent.
- One Sonarr and one Radarr instance. No 4K-instance split yet.
- One stats view buckets movie watch time under a library named "Movies";
  if your movie library is named something else that row will be off.
- Deleting is done through the Sonarr/Radarr APIs, never the filesystem
  directly, so recycle-bin settings in the arrs apply as usual.

## Development

Backend is FastAPI (Python 3.12), frontend is React + Vite + Tailwind. The
Dockerfile builds both; for local hacking:

```bash
cd frontend && npm install && npm run dev   # frontend on :5173, proxies /api
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload           # backend on :8000
```

## License

MIT — see [LICENSE](LICENSE).
