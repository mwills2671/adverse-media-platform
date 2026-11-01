import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, Meta, setCsrf, User } from "./api";
import Login from "./pages/Login";
import NewScreening from "./pages/NewScreening";
import ScreeningPage from "./pages/Screening";
import History from "./pages/History";
import Admin from "./pages/Admin";
import Audit from "./pages/Audit";

type Ctx = { user: User | null; meta: Meta | null; setUser: (u: User | null) => void; can: (a: "write" | "admin") => boolean };
const AuthCtx = createContext<Ctx>({ user: null, meta: null, setUser: () => {}, can: () => false });
export const useAuth = () => useContext(AuthCtx);

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [loading, setLoading] = useState(true);
  const [menu, setMenu] = useState(false);
  const nav = useNavigate();

  useEffect(() => {
    api("/auth/me").then(r => { setCsrf(r.csrf); setUser(r.user); }).catch(() => {}).finally(() => setLoading(false));
    const h = () => setUser(null);
    window.addEventListener("ams-unauth", h);
    return () => window.removeEventListener("ams-unauth", h);
  }, []);
  useEffect(() => { if (user) api<Meta>("/meta").then(setMeta).catch(() => {}); }, [user]);

  const can = useCallback((a: "write" | "admin") =>
    !!user && (a === "admin" ? user.role === "admin" : user.role !== "readonly"), [user]);

  const logout = async () => { try { await api("/auth/logout", { method: "POST" }); } catch { /* */ } setUser(null); nav("/"); };

  if (loading) return <div className="p-8 text-slate-500">Loading…</div>;
  if (!user) return <Login onLogin={u => setUser(u)} />;

  const link = ({ isActive }: { isActive: boolean }) =>
    `block px-3 py-2 rounded text-sm font-medium ${isActive ? "bg-indigo-800 text-white" : "text-indigo-100 hover:bg-indigo-800/60"}`;
  return <AuthCtx.Provider value={{ user, meta, setUser, can }}>
    <header className="bg-indigo-900 text-white">
      <div className="max-w-7xl mx-auto px-3 sm:px-6 flex items-center justify-between h-14">
        <Link to="/" className="font-semibold tracking-tight flex items-center gap-2">
          <span className="bg-white text-indigo-900 rounded px-1.5 py-0.5 text-xs font-black">AMS</span>
          <span className="hidden sm:inline">Adverse Media Screening</span>
        </Link>
        <nav className="hidden md:flex gap-1" aria-label="Main">
          {can("write") && <NavLink to="/" end className={link}>New screening</NavLink>}
          <NavLink to="/history" className={link}>History</NavLink>
          {user.role !== "readonly" && <NavLink to="/audit" className={link}>Audit log</NavLink>}
          {can("admin") && <NavLink to="/admin" className={link}>Admin</NavLink>}
        </nav>
        <div className="hidden md:flex items-center gap-3 text-sm">
          <span className="text-indigo-200">{user.username} · {user.role}</span>
          <button className="btn-secondary !py-1" onClick={logout}>Sign out</button>
        </div>
        <button className="md:hidden btn !text-white" aria-label="Menu" aria-expanded={menu} onClick={() => setMenu(!menu)}>☰</button>
      </div>
      {menu && <nav className="md:hidden px-3 pb-3 space-y-1" onClick={() => setMenu(false)} aria-label="Mobile">
        {can("write") && <NavLink to="/" end className={link}>New screening</NavLink>}
        <NavLink to="/history" className={link}>History</NavLink>
        {user.role !== "readonly" && <NavLink to="/audit" className={link}>Audit log</NavLink>}
        {can("admin") && <NavLink to="/admin" className={link}>Admin</NavLink>}
        <div className="flex items-center justify-between pt-2 text-sm text-indigo-200">
          <span>{user.username} · {user.role}</span>
          <button className="btn-secondary !py-1" onClick={logout}>Sign out</button>
        </div>
      </nav>}
    </header>
    {meta?.test_mode && <div className="bg-fuchsia-700 text-white text-center text-xs py-1 font-semibold">TEST MODE — labelled fixtures and fault injection available. Not for production use.</div>}
    <main className="max-w-7xl mx-auto px-3 sm:px-6 py-4 sm:py-6">
      <Routes>
        <Route path="/" element={can("write") ? <NewScreening /> : <Navigate to="/history" />} />
        <Route path="/screenings/:id" element={<ScreeningPage />} />
        <Route path="/history" element={<History />} />
        <Route path="/audit" element={<Audit />} />
        <Route path="/admin" element={can("admin") ? <Admin /> : <Navigate to="/" />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </main>
    <footer className="max-w-7xl mx-auto px-3 sm:px-6 pb-6 text-xs text-slate-500">
      Results reflect only the sources searched on the screening date and support — not replace — analyst judgement.
      Sanctions/PEP screening is a separate process.
    </footer>
  </AuthCtx.Provider>;
}
