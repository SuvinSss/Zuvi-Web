import { useState, type FormEvent } from "react";
import { Alert, Button, Empty, ErrorRetry, Field, Loading } from "../../components/ui";
import { get, messageOf, post } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { useLoad } from "../../lib/useAsync";
import type { AdminAssignment } from "../../lib/types";

interface Payload {
  assignments: AdminAssignment[];
  agents: { id: number; username: string; name: string }[];
}

export function AdminAssignments() {
  const d = useLoad(() => get<Payload>("/admin/assignments/"));
  const [order, setOrder] = useState("");
  const [agent, setAgent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/admin/assignments/", { store_order_number: order.trim(), agent_id: Number(agent) });
      setOrder("");
      d.reload();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  if (d.loading && !d.data) return <Loading />;
  if (d.error) return <ErrorRetry message={d.error} onRetry={d.reload} />;
  return (
    <div>
      <h1>Delivery assignments</h1>
      <form className="card" onSubmit={(e) => void submit(e)}>
        <h2>Assign a delivery partner</h2>
        {error && <Alert>{error}</Alert>}
        <Field label="Store order number">
          {({ id }) => <input id={id} value={order} onChange={(e) => setOrder(e.target.value)} />}
        </Field>
        <Field label="Delivery partner">
          {({ id }) => (
            <select id={id} value={agent} onChange={(e) => setAgent(e.target.value)}>
              <option value="">Choose…</option>
              {d.data?.agents.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.username})</option>)}
            </select>
          )}
        </Field>
        <Button type="submit" disabled={busy || !order.trim() || !agent}>{busy ? "Assigning…" : "Assign"}</Button>
      </form>
      <section className="card table-wrap">
        <h2>Recent assignments</h2>
        {d.data?.assignments.length === 0 && <Empty>Nothing assigned yet.</Empty>}
        <table>
          <thead><tr><th>Order</th><th>Store</th><th>Partner</th><th>Status</th><th>Assigned</th></tr></thead>
          <tbody>
            {d.data?.assignments.map((a) => (
              <tr key={a.id}><td>{a.store_order_number}</td><td>{a.store_name}</td><td>{a.agent_username}</td><td>{a.status}</td><td>{formatDateTime(a.assigned_at)}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
