import os

PLEX_TOKEN = os.environ.get("PLEX_TOKEN", "")
PLEX_SERVER_URL = os.environ.get("PLEX_SERVER_URL", "http://localhost:32400").rstrip("/")
SONARR_URL = os.environ.get("SONARR_URL", "").rstrip("/")
SONARR_API_KEY = os.environ.get("SONARR_API_KEY", "")
RADARR_URL = os.environ.get("RADARR_URL", "").rstrip("/")
RADARR_API_KEY = os.environ.get("RADARR_API_KEY", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
TAUTULLI_URL = os.environ.get("TAUTULLI_URL", "").rstrip("/")
TAUTULLI_API_KEY = os.environ.get("TAUTULLI_API_KEY", "")

# Where users are sent to request media that isn't in the library yet
# (Overseerr, Jellyseerr, Ombi...). Unset hides the request links entirely.
REQUEST_URL = os.environ.get("REQUEST_URL", "").rstrip("/")

# Library titles to hide from recently-watched and stats surfaces,
# comma-separated (e.g. "Fitness,Home Videos"). Unset hides nothing.
HIDDEN_LIBRARIES = {
    name.strip() for name in os.environ.get("HIDDEN_LIBRARIES", "").split(",") if name.strip()
}

# Push notifications (optional — unset means push is simply off).
APNS_KEY_PATH = os.environ.get("APNS_KEY_PATH", "")
APNS_KEY_ID = os.environ.get("APNS_KEY_ID", "")
APNS_TEAM_ID = os.environ.get("APNS_TEAM_ID", "")
APNS_BUNDLE_ID = os.environ.get("APNS_BUNDLE_ID", "")
APNS_USE_SANDBOX = os.environ.get("APNS_USE_SANDBOX", "").lower() == "true"
