import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { get, post } from "../lib/api";
import type { MapsConfig, Portal, Session } from "../lib/types";

interface SessionState {
  session: Session | null;
  loading: boolean;
  error: string | null;
  mapsConfig: MapsConfig | null;
  refresh: () => Promise<void>;
  login: (portal: Portal, username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [mapsConfig, setMapsConfig] = useState<MapsConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([get<Session>("/auth/session/"), get<MapsConfig>("/config/maps/")]);
      setSession(s);
      setMapsConfig(c);
      setError(null);
    } catch {
      setError("We couldn't load ZuuVi. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Initial session load on mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  const login = useCallback(async (portal: Portal, username: string, password: string) => {
    const s = await post<Session>("/auth/login/", { username, password, portal });
    setSession(s);
  }, []);

  const logout = useCallback(async () => {
    await post("/auth/logout/");
    setSession({ authenticated: false });
  }, []);

  const value = useMemo(
    () => ({ session, loading, error, mapsConfig, refresh, login, logout }),
    [session, loading, error, mapsConfig, refresh, login, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): SessionState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession must be used inside SessionProvider");
  return v;
}
