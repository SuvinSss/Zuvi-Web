import { useState } from "react";
import { Alert, Button, Empty, ErrorRetry, Loading } from "../../components/ui";
import { del, get, messageOf, post } from "../../lib/api";
import { parsePoint, shortAddress } from "../../lib/format";
import { useLoad } from "../../lib/useAsync";
import type { SavedAddress } from "../../lib/types";
import { useSelectedLocation } from "../../state/location";

export function Addresses() {
  const { select, openDialog } = useSelectedLocation();
  const list = useLoad(async () => (await get<{ addresses: SavedAddress[] }>("/customer/addresses/")).addresses);
  const [error, setError] = useState<string | null>(null);

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      list.reload();
    } catch (e) {
      setError(messageOf(e));
    }
  }

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Saved addresses</h1>
        <Button onClick={openDialog}>Add address</Button>
      </div>
      {error && <Alert>{error}</Alert>}
      {list.loading && <Loading />}
      {list.error && <ErrorRetry message={list.error} onRetry={list.reload} />}
      {list.data?.length === 0 && <Empty>You haven't saved an address yet.</Empty>}
      <div className="grid">
        {list.data?.map((a) => {
          const pt = parsePoint(a.latitude, a.longitude);
          return (
            <article className="card" key={a.id}>
              <h2>
                {a.label_display} {a.is_default && <span className="badge">Default</span>}
              </h2>
              <p>{a.recipient_name} · {a.phone_number}</p>
              <p className="muted">{shortAddress(a)}, {a.postal_code}</p>
              {!a.location_confirmed && (
                <Alert kind="warn">The pin for this address hasn't been confirmed. Re-add it to confirm.</Alert>
              )}
              <div className="row">
                <Button
                  variant="secondary"
                  disabled={!pt}
                  onClick={() => pt && select({ label: a.label_display, title: shortAddress(a), point: pt, addressId: a.id })}
                >
                  Deliver here
                </Button>
                {!a.is_default && (
                  <Button variant="link" onClick={() => void act(() => post(`/customer/addresses/${a.id}/default/`))}>
                    Make default
                  </Button>
                )}
                <Button variant="link" onClick={() => void act(() => del(`/customer/addresses/${a.id}/`))} aria-label={`Delete ${a.label_display} address`}>
                  Delete
                </Button>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
