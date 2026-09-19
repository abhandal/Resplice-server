import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Login() {
  const { user, loading, loginError, loginWithPlex, cancelLogin } = useAuth();

  if (user) return <Navigate to="/" />;

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center px-6">
        <div className="text-center">
          <div className="w-10 h-10 border-3 border-purple-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-400 text-sm">Signing you in...</p>
          <button
            onClick={cancelLogin}
            className="mt-4 text-sm text-gray-500 hover:text-gray-300 underline transition-colors"
          >
            Cancel and start over
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-6">
      <div className="text-center max-w-sm">
        <h1 className="text-4xl font-bold mb-2 bg-gradient-to-r from-indigo-500 to-purple-500 bg-clip-text text-transparent">
          Plex Support
        </h1>
        <p className="text-gray-400 mb-8">
          Report broken playback and we'll fix it for you
        </p>
        {loginError && (
          <div className="mb-4 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-sm text-left">
            {loginError}
          </div>
        )}
        <button
          onClick={loginWithPlex}
          className="w-full py-3 px-6 rounded-xl font-semibold text-white bg-gradient-to-r from-indigo-500 to-purple-500 hover:from-indigo-600 hover:to-purple-600 transition-all shadow-lg shadow-purple-500/25"
        >
          {loginError ? "Try again" : "Sign in with Plex"}
        </button>
      </div>
    </div>
  );
}
