import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { api } from "../api";

interface User {
  id: number;
  username: string;
  thumb: string;
  isAdmin?: boolean;
  requestUrl?: string | null;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  loginError: string;
  loginWithPlex: () => void;
  logout: () => Promise<void>;
  clearLoginError: () => void;
  cancelLogin: () => void;
}

const AuthContext = createContext<AuthContextType>(null!);
export const useAuth = () => useContext(AuthContext);

const CLIENT_ID_KEY = "plex_support_client_id";
const PIN_ID_KEY = "plex_support_pin_id";
const PIN_TS_KEY = "plex_support_pin_ts";

// Plex PINs expire server-side (~15 min). Polling one older than that can never
// yield a token, so a leftover PIN must be discarded rather than waited on —
// otherwise an abandoned sign-in strands the user on the spinner forever.
const PIN_TTL_MS = 15 * 60 * 1000;

function clearPinState() {
  localStorage.removeItem(CLIENT_ID_KEY);
  localStorage.removeItem(PIN_ID_KEY);
  localStorage.removeItem(PIN_TS_KEY);
}

// crypto.randomUUID() is only exposed in secure contexts (HTTPS or localhost).
// This app is also served over plain HTTP on the LAN, where it is undefined —
// calling it threw and silently killed the sign-in click. getRandomValues() is
// NOT secure-context gated, so build the v4 UUID from it instead.
function uuidv4(): string {
  if (crypto.randomUUID) return crypto.randomUUID();

  const bytes = new Uint8Array(16);
  if (crypto.getRandomValues) {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10

  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [loginError, setLoginError] = useState("");

  const clearLoginError = () => setLoginError("");

  // Escape hatch: the spinner must never be a screen with no way out.
  const cancelLogin = () => {
    clearPinState();
    setLoading(false);
    setLoginError("");
  };

  // Check for returning from Plex auth redirect
  useEffect(() => {
    const savedClientId = localStorage.getItem(CLIENT_ID_KEY);
    const savedPinId = localStorage.getItem(PIN_ID_KEY);
    const savedAt = Number(localStorage.getItem(PIN_TS_KEY)) || 0;

    // A PIN we can still exchange. Anything else — abandoned sign-in, expired
    // PIN, or keys from before PIN_TS_KEY existed — is dead weight: drop it and
    // fall through to the normal session check so the user gets the button back.
    const pinIsLive =
      !!savedClientId && !!savedPinId && Date.now() - savedAt < PIN_TTL_MS;

    if ((savedClientId || savedPinId) && !pinIsLive) {
      clearPinState();
    }

    if (pinIsLive) {
      // We're returning from Plex auth — poll for the token
      let cancelled = false;
      const stopPolling = () => {
        cancelled = true;
        clearInterval(interval);
        clearTimeout(timeout);
        clearPinState();
      };

      const interval = setInterval(async () => {
        if (cancelled) return;
        let authToken = "";
        try {
          const resp = await fetch(`https://plex.tv/api/v2/pins/${savedPinId}`, {
            headers: {
              Accept: "application/json",
              "X-Plex-Client-Identifier": savedClientId,
            },
          });
          const data = await resp.json();
          authToken = data.authToken || "";
        } catch {
          return; // network blip, keep polling
        }
        if (!authToken) return;

        // Got the token — stop polling and exchange it with our backend.
        // Any error from /auth/plex must surface to the user; otherwise the
        // Login page sits on "Signing you in..." until the 2-minute timeout.
        stopPolling();
        try {
          const userData = await api.authPlex(authToken);
          setUser(userData);
        } catch (e: any) {
          setLoginError(e?.message || "Sign-in failed. Please try again.");
        } finally {
          setLoading(false);
        }
      }, 1500);

      // Timeout after 2 minutes
      const timeout = setTimeout(() => {
        if (cancelled) return;
        stopPolling();
        setLoginError("Sign-in timed out. Please try again.");
        setLoading(false);
      }, 120000);

      // Don't call authMe — we're handling auth via the PIN
      return () => stopPolling();
    }

    // Normal load — check existing session
    api.authMe().then(setUser).catch(() => setUser(null)).finally(() => setLoading(false));
  }, []);

  const loginWithPlex = async () => {
    setLoginError("");

    // Everything here must be guarded: this runs from onClick, so a rejected
    // promise is discarded by React and the button just appears dead.
    try {
      const clientId = "plex-support-" + uuidv4();

      const resp = await fetch("https://plex.tv/api/v2/pins?strong=true", {
        method: "POST",
        headers: {
          Accept: "application/json",
          "X-Plex-Client-Identifier": clientId,
          "X-Plex-Product": "Plex Support",
        },
      });
      if (!resp.ok) throw new Error(`Plex returned ${resp.status}. Please try again.`);

      const pin = await resp.json();
      if (!pin?.id || !pin?.code) throw new Error("Plex didn't return a valid PIN.");

      // Save state for when we return, stamped so a sign-in the user abandons
      // ages out instead of trapping them on the spinner on every later visit.
      localStorage.setItem(CLIENT_ID_KEY, clientId);
      localStorage.setItem(PIN_ID_KEY, String(pin.id));
      localStorage.setItem(PIN_TS_KEY, String(Date.now()));

      // Redirect to Plex auth in same tab (works on mobile)
      const forwardUrl = window.location.origin + "/login";
      window.location.href =
        `https://app.plex.tv/auth#?clientID=${clientId}&code=${pin.code}` +
        `&context%5Bdevice%5D%5Bproduct%5D=Plex%20Support` +
        `&forwardUrl=${encodeURIComponent(forwardUrl)}`;
    } catch (e: any) {
      setLoginError(e?.message || "Couldn't reach Plex. Please try again.");
    }
  };

  const logout = async () => {
    await api.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{ user, loading, loginError, loginWithPlex, logout, clearLoginError, cancelLogin }}
    >
      {children}
    </AuthContext.Provider>
  );
}
