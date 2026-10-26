import { Empty, ErrorRetry, Loading } from "../../components/ui";
import { get } from "../../lib/api";
import { useLoad } from "../../lib/useAsync";
import type { FulfilmentOrder } from "../../lib/types";

export function StoreOrdersPage() {
  const o = useLoad(async () => (await get<{ orders: FulfilmentOrder[] }>("/store/orders/")).orders);
  if (o.loading) return <Loading />;
  if (o.error) return <ErrorRetry message={o.error} onRetry={o.reload} />;
  return (
    <div>
      <h1>Delivery orders</h1>
      {o.data?.length === 0 && <Empty>No delivery orders yet.</Empty>}
      <div className="grid">
        {o.data?.map((x) => (
          <article className="card" key={x.store_order_number}>
            <h2>{x.store_order_number}</h2>
            <span className="badge">{x.status_display}</span>
            {x.dropoff ? (
              <>
                <p>{x.dropoff.recipient_name} · {x.dropoff.phone_number}</p>
                <p className="muted">{[x.dropoff.line1, x.dropoff.landmark, x.dropoff.city].filter(Boolean).join(", ")}</p>
                <a href={x.dropoff.navigation_url} target="_blank" rel="noopener noreferrer">Open in Google Maps</a>
              </>
            ) : (
              <p className="muted">Customer address is shown once you accept the order.</p>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}
