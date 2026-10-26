import { APIProvider } from "@vis.gl/react-google-maps";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useSession } from "./session";

export type MapsAvailability =
  | { status: "ready"; mapId: string }
  | { status: "unconfigured" }
  | { status: "rejected" }
  | { status: "loading" };

const Ctx = createContext<MapsAvailability>({ status: "unconfigured" });

declare global {
  interface Window {
    gm_authFailure?: () => void;
  }
}

/**
 * Loads Google Maps with the browser key only. When the key is missing or Google
 * rejects it, `status` tells screens to fall back to manual address entry instead
 * of showing a broken map.
 */
export function MapsProvider({ children }: { children: ReactNode }) {
  const { mapsConfig, loading } = useSession();
  const [rejected, setRejected] = useState(false);

  useEffect(() => {
    window.gm_authFailure = () => setRejected(true);
    return () => {
      delete window.gm_authFailure;
    };
  }, []);

  const availability: MapsAvailability = useMemo(() => {
    if (loading) return { status: "loading" };
    if (!mapsConfig?.browserConfigured) return { status: "unconfigured" };
    if (rejected) return { status: "rejected" };
    return { status: "ready", mapId: mapsConfig.mapId || "DEMO_MAP_ID" };
  }, [loading, mapsConfig, rejected]);

  if (availability.status === "ready" && mapsConfig) {
    return (
      <Ctx.Provider value={availability}>
        <APIProvider
          apiKey={mapsConfig.browserKey}
          region={mapsConfig.region}
          language={mapsConfig.language}
          libraries={["places", "marker"]}
          onError={() => setRejected(true)}
        >
          {children}
        </APIProvider>
      </Ctx.Provider>
    );
  }
  return <Ctx.Provider value={availability}>{children}</Ctx.Provider>;
}

export function useMapsAvailability(): MapsAvailability {
  return useContext(Ctx);
}

export function mapsUnavailableMessage(a: MapsAvailability): string {
  if (a.status === "rejected")
    return "Google Maps rejected this site's key, so the map can't load. You can still type your address.";
  return "Maps aren't available right now. You can still type your address.";
}
