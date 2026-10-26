import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { readJson, removeKey, writeJson } from "../lib/storage";
import type { Point } from "../lib/types";

export interface SelectedLocation {
  label: string;
  title: string;
  point: Point;
  addressId: number | null;
}

const KEY = "zuuvi.selectedLocation.v1";

interface LocationState {
  selected: SelectedLocation | null;
  select: (l: SelectedLocation) => void;
  clear: () => void;
  dialogOpen: boolean;
  openDialog: () => void;
  closeDialog: () => void;
}

const Ctx = createContext<LocationState | null>(null);

function validStored(v: SelectedLocation | null): SelectedLocation | null {
  if (!v || typeof v.title !== "string" || !v.point) return null;
  return Number.isFinite(v.point.lat) && Number.isFinite(v.point.lng) ? v : null;
}

export function LocationProvider({ children }: { children: ReactNode }) {
  const [selected, setSelected] = useState<SelectedLocation | null>(() => validStored(readJson(KEY)));
  const [dialogOpen, setDialogOpen] = useState(false);

  const select = useCallback((l: SelectedLocation) => {
    setSelected(l);
    writeJson(KEY, l);
  }, []);
  const clear = useCallback(() => {
    setSelected(null);
    removeKey(KEY);
  }, []);

  const value = useMemo(
    () => ({
      selected,
      select,
      clear,
      dialogOpen,
      openDialog: () => setDialogOpen(true),
      closeDialog: () => setDialogOpen(false),
    }),
    [selected, select, clear, dialogOpen],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSelectedLocation(): LocationState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSelectedLocation must be used inside LocationProvider");
  return v;
}
