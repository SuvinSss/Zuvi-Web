import { AdvancedMarker, Map } from "@vis.gl/react-google-maps";
import { useState } from "react";
import { StoreLocationEditor } from "../../components/StoreLocationEditor";
import { Alert, Button, ErrorRetry, Loading } from "../../components/ui";
import { get } from "../../lib/api";
import { parsePoint } from "../../lib/format";
import { useLoad } from "../../lib/useAsync";
import type { StoreLocation } from "../../lib/types";
import { useMapsAvailability } from "../../state/maps";

export function AdminStores() {
  const maps = useMapsAvailability();
  const list = useLoad(() => get<{ stores: StoreLocation[]; needs_attention: number }>("/admin/stores/locations/"));
  const [editing, setEditing] = useState<number | null>(null);

  if (list.loading && !list.data) return <Loading />;
  if (list.error) return <ErrorRetry message={list.error} onRetry={list.reload} />;
  if (!list.data) return null;
  const stores = list.data.stores;
  const first = stores.map((s) => parsePoint(s.latitude, s.longitude)).find(Boolean);

  return (
    <div>
      <h1>Store locations</h1>
      {list.data.needs_attention > 0 ? (
        <Alert kind="warn">{list.data.needs_attention} store(s) need a location fix before they can take delivery orders.</Alert>
      ) : (
        <Alert kind="info">All stores have confirmed locations.</Alert>
      )}
      {maps.status === "ready" && first && (
        <div className="map-box" style={{ marginBottom: "1rem" }} data-testid="stores-map">
          <Map mapId={maps.mapId} defaultCenter={first} defaultZoom={11} disableDefaultUI zoomControl gestureHandling="cooperative">
            {stores.map((s) => {
              const p = parsePoint(s.latitude, s.longitude);
              return p && <AdvancedMarker key={s.id} position={p} title={s.name} />;
            })}
          </Map>
        </div>
      )}
      <div className="table-wrap card">
        <table>
          <thead><tr><th>Store</th><th>Status</th><th>Radius</th><th>Location</th><th /></tr></thead>
          <tbody>
            {stores.map((s) => (
              <tr key={s.id}>
                <td>{s.name}<br /><span className="muted">{s.store_code}</span></td>
                <td>{s.status}</td>
                <td>{s.delivery_radius_km} km</td>
                <td>
                  {s.can_take_delivery_orders ? <span className="badge live">Ready</span> : <span className="badge">Needs fix</span>}
                  {s.issues.map((i) => <div key={i.code} className="muted">{i.message}</div>)}
                </td>
                <td><Button variant="secondary" onClick={() => setEditing(editing === s.id ? null : s.id)}>{editing === s.id ? "Close" : "Edit"}</Button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {stores.filter((s) => s.id === editing).map((s) => (
        <div className="card" key={s.id}>
          <h2>{s.name}</h2>
          <StoreLocationEditor store={s} endpoint={`/admin/stores/${s.id}/location/`} allowRadius onSaved={() => { setEditing(null); list.reload(); }} />
        </div>
      ))}
    </div>
  );
}
