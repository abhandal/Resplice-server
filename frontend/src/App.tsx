import { Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { QueueProvider } from "./context/QueueContext";
import Login from "./pages/Login";
import Search from "./pages/Search";
import Seasons from "./pages/Seasons";
import Episodes from "./pages/Episodes";
import Admin from "./pages/Admin";
import Stats from "./pages/Stats";
import Navbar from "./components/Navbar";
import QueueBar from "./components/QueueBar";
import PullToRefresh from "./components/PullToRefresh";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center text-gray-500">Loading...</div>;
  if (!user) return <Navigate to="/login" />;
  return <>{children}</>;
}

function Layout() {
  return (
    <QueueProvider>
      <PullToRefresh>
        <div className="min-h-screen pb-20">
          <Navbar />
          <Routes>
            <Route path="/" element={<Search />} />
            <Route path="/series/:id" element={<Seasons />} />
            <Route path="/series/:id/season/:season" element={<Episodes />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/stats" element={<Stats />} />
          </Routes>
          <QueueBar />
        </div>
      </PullToRefresh>
    </QueueProvider>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
