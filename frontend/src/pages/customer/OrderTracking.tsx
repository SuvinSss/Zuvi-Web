import { AdvancedMarker, Map } from "@vis.gl/react-google-maps";
import { useParams } from "react-router-dom";
import { Alert, ErrorRetry, Loading } from "../../components/ui";
import { get } from "../../lib/api";
import { money, parsePoint } from "../../lib/format";
import { useLoad } from "../../lib/useAsync";
import type { OrderTracking as Tracking } from "../../lib/types";
import { useMapsAvailability } from "../../state/maps";

export function OrderTracking() {
  const { orderNumber = "" } = useParams();
  const maps = useMapsAvailability();
  const t = useLoad(() => get<Tracking>(`/customer/orders/${encodeURIComponent(orderNumber)}/tracking/`), [orderNumber]);

  if (t.loading) return <Loading />;
  if (t.error) return <ErrorRetry message={t.error} onRetry={t.reload} />;
  if (!t.data) return null;
  const o = t.data;
  const drop = parsePoint(o.delivery.latitude, o.delivery.longitude);
  const pickups = o.stores.map((s) => parsePoint(s.pickup.latitude, s.pickup.longitude));
  const first = pickups.find(Boolean) ?? drop;

  return (
    <div>
      <h1>Order {o.order_number}</h1>
      <p><span className="badge">{o.status_display}</span></p>
      {maps.status === "ready" && first ? (
        <div className="map-box" data-testid="tracking-map">
          <Map mapId={maps.mapId} defaultCenter={first} defaultZoom={13} disableDefaultUI zoomControl gestureHandling="cooperative">
            {pickups.map((p, i) => p && <AdvancedMarker key={i} position={p} title={o.stores[i]?.store_name ?? "Store"} />)}
            {drop && <AdvancedMarker position={drop} title="Delivery address" />}
          </Map>
        </div>
      ) : (
        <Alert kind="info">The map isn't available, but your order status below is up to date.</Alert>
      )}
      <section className="card" style={{ marginTop: "1rem" }}>
        <h2>Delivering to</h2>
        <p>{o.delivery.label || "—"}</p>
        <p className="muted">{o.delivery_time_note}</p>
        <h2>From</h2>
        <ul>
          {o.stores.map((s, i) => (
            <li key={i}>
              {s.store_name} — {s.status_display}
              {s.delivery_partner_status && <> · delivery partner: {s.delivery_partner_status}</>}
            </li>
          ))}
        </ul>
        <dl className="fee-breakdown">
          <dt>Delivery fee</dt><dd>{money(o.delivery_charge)}</dd>
          <dt>Total</dt><dd>{money(o.grand_total)}</dd>
        </dl>
      </section>
    </div>
  );
}
