import { useCallback, useEffect, useRef, useState } from "react";
import { messageOf } from "./api";

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
  setData: (d: T | null) => void;
}

/** Load once on mount (and on reload). Ignores responses from superseded calls. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const latest = useRef(0);

  useEffect(() => {
    const mine = ++latest.current;
    // Starting a fetch legitimately flips the loading flag on the same tick.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    fn()
      .then((d) => {
        if (mine === latest.current) {
          setData(d);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (mine === latest.current) setError(messageOf(e));
      })
      .finally(() => {
        if (mine === latest.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, loading, error, reload, setData };
}
