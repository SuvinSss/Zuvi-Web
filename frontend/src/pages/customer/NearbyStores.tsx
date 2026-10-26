import { Alert, Button, Empty, ErrorRetry, Loading } from "../../components/ui";
import { get } from "../../lib/api";
import { useLoad } from "../../lib/useAsync";
import type { NearbyStore } from "../../lib/types";
import { useSelectedLocation } from "../../state/location";

export function NearbyStores() {
  const { selected, openDialog } = useSelectedLocation();
  const lat = selected?.point.lat;
  const lng = selected?.point.lng;
  const stores = useLoad(
    async () =>
      selected
        ? (await get<{ stores: NearbyStore[] }>(`/stores/nearby/?lat=${lat}&lng=${lng}`)).stores
        : [],
    [lat, lng],
  );

  return (
    <div>
      <h1>Stores near you</h1>
      {!selected ? (
        <div className="card">
          <p>Choose where to deliver and we'll show the stores that can reach you.</p>
          <Button onClick={openDialog}>Choose your location</Button>
        </div>
      ) : (
        <>
          <Alert kind="info">
            Availability here is approximate. The exact delivery distance and fee are confirmed at checkout.
          </Alert>
          {stores.loading && <Loading label="Finding stores…" />}
          {stores.error && <ErrorRetry message={stores.error} onRetry={stores.reload} />}
          {stores.data && stores.data.length === 0 && !stores.loading && (
            <Empty>No stores deliver to this location yet.</Empty>
          )}
          <div className="grid">
            {stores.data?.map((s) => (
              <article className="card" key={s.id}>
                <h2>{s.name}</h2>
                <p className="muted">{s.category}</p>
                {s.within_delivery_area ? (
                  <span className="badge live">Delivers to you</span>
                ) : (
                  <>
                    <span className="badge">Not available</span>
                    {s.reasons[0] && <p className="muted">{s.reasons[0].message}</p>}
                  </>
                )}
                {s.straight_line_km !== null && (
                  <p className="muted">About {s.straight_line_km.toFixed(1)} km away (straight line)</p>
                )}
              </article>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
