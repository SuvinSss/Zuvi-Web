import { useState } from "react";
import { Alert, Button, Empty, ErrorRetry, Loading } from "../../components/ui";
import { get, messageOf, post } from "../../lib/api";
import { useLoad } from "../../lib/useAsync";
import type { AddressBlock, RiderAssignment } from "../../lib/types";

function Place({ title, a }: { title: string; a: AddressBlock }) {
  return (
    <div>
      <h3>{title}</h3>
      <p>{[a.line1, a.line2, a.landmark, a.city, a.postal_code].filter(Boolean).join(", ")}</p>
      {a.recipient_name && <p className="muted">{a.recipient_name} · {a.phone_number}</p>}
      <a className="btn secondary" style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }} href={a.navigation_url} target="_blank" rel="noopener noreferrer">
        Navigate in Google Maps
      </a>
    </div>
  );
}

export function Assignments() {
  const list = useLoad(async () => (await get<{ assignments: RiderAssignment[] }>("/rider/assignments/")).assignments);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  async function advance(a: RiderAssignment) {
    setBusyId(a.id);
    setError(null);
    try {
      await post(`/rider/assignments/${a.id}/advance/`);
      list.reload();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <h1>My deliveries</h1>
      {error && <Alert>{error}</Alert>}
      {list.loading && <Loading />}
      {list.error && <ErrorRetry message={list.error} onRetry={list.reload} />}
      {list.data?.length === 0 && <Empty>No active deliveries right now.</Empty>}
      {list.data?.map((a) => (
        <article className="card" key={a.id}>
          <h2>{a.store_order_number}</h2>
          <p>
            <span className="badge">{a.status_display}</span> <span className="badge">Store: {a.store_order_status_display}</span>
          </p>
          {a.route && (
            <p>
              About {a.route.distance_km} km · {a.route.duration_minutes} min{" "}
              <span className={`badge ${a.route.source === "LIVE" ? "live" : "cached"}`}>{a.route.source}</span>
            </p>
          )}
          <div className="grid">
            <Place title="Pick up" a={a.pickup} />
            {a.dropoff && <Place title="Drop off" a={a.dropoff} />}
          </div>
          {a.delivery_instructions && <Alert kind="info">Instructions: {a.delivery_instructions}</Alert>}
          {a.next_action && (
            <div className="row" style={{ marginTop: ".75rem" }}>
              <span>{a.next_action.label}</span>
              {a.next_action.code !== "WAIT" && a.next_action.code !== "HAND_OVER" && (
                <Button onClick={() => void advance(a)} disabled={busyId === a.id}>
                  {a.next_action.code === "PICK_UP" ? "I've picked it up" : "I've arrived"}
                </Button>
              )}
            </div>
          )}
        </article>
      ))}
    </div>
  );
}
