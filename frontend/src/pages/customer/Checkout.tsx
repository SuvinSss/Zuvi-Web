import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Empty, ErrorRetry, Field, Loading } from "../../components/ui";
import { ApiError, get, messageOf, post } from "../../lib/api";
import { money, shortAddress } from "../../lib/format";
import { useLoad } from "../../lib/useAsync";
import type { CheckoutSummary, DeliveryQuote } from "../../lib/types";
import { useSelectedLocation } from "../../state/location";

export function Checkout() {
  const navigate = useNavigate();
  const { selected } = useSelectedLocation();
  const summary = useLoad(() => get<CheckoutSummary>("/customer/checkout/summary/"));
  const [addressId, setAddressId] = useState<number | null>(null);
  const [quote, setQuote] = useState<DeliveryQuote | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteError, setQuoteError] = useState<ApiError | string | null>(null);
  const [notes, setNotes] = useState("");
  const [placing, setPlacing] = useState(false);
  const [placeError, setPlaceError] = useState<string | null>(null);

  // Default to the address chosen in the header, else the default saved address.
  const addresses = summary.data?.addresses ?? [];
  const effectiveId =
    addressId ??
    (addresses.find((a) => a.id === selected?.addressId) ?? addresses.find((a) => a.is_default) ?? addresses[0])?.id ??
    null;
  // A quote belongs to one basket and one address: ignore it if the address differs.
  const activeQuote = quote && quote.address_id === effectiveId ? quote : null;

  function chooseAddress(id: number) {
    setAddressId(id);
    setQuote(null);
    setQuoteError(null);
  }

  async function getQuote() {
    if (effectiveId === null) return;
    setQuoting(true);
    setQuoteError(null);
    try {
      setQuote(await post<DeliveryQuote>("/customer/delivery-quote/", { address_id: effectiveId }));
    } catch (e) {
      setQuote(null);
      setQuoteError(e instanceof ApiError ? e : messageOf(e));
    } finally {
      setQuoting(false);
    }
  }

  async function place() {
    if (!summary.data || !activeQuote || effectiveId === null) return;
    setPlacing(true);
    setPlaceError(null);
    try {
      const order = await post<{ order_number: string }>("/customer/checkout/", {
        address_id: effectiveId,
        quote_id: activeQuote.id,
        checkout_token: summary.data.checkout_token,
        customer_notes: notes,
      });
      navigate(`/customer/orders/${order.order_number}`, { replace: true });
    } catch (e) {
      setPlaceError(messageOf(e));
      if (e instanceof ApiError && /quote|expired|changed/i.test(e.message)) setQuote(null);
    } finally {
      setPlacing(false);
    }
  }

  if (summary.loading) return <Loading />;
  if (summary.error) return <ErrorRetry message={summary.error} onRetry={summary.reload} />;
  const data = summary.data;
  if (!data) return null;
  if (data.cart.is_empty)
    return (
      <div>
        <h1>Checkout</h1>
        <Empty>Your basket is empty. Add items from the store pages first.</Empty>
        <a href="/">Browse stores</a>
      </div>
    );

  const quoteMessage = quoteError instanceof ApiError ? quoteError : null;
  return (
    <div>
      <h1>Checkout</h1>
      {data.cart.blocking_messages.map((m) => (
        <Alert key={m} kind="warn">{m}</Alert>
      ))}
      <section className="card">
        <h2>Your basket</h2>
        {data.cart.stores.map((g) => (
          <div key={g.store_id}>
            <strong>{g.store_name}</strong> <span className="muted">{money(g.items_subtotal)}</span>
            <ul>
              {g.items.map((i, idx) => (
                <li key={idx}>
                  {i.quantity} × {i.product_name} {i.line_total && <span className="muted">{money(i.line_total)}</span>}
                </li>
              ))}
            </ul>
          </div>
        ))}
        <p>Items total: <strong>{money(data.cart.items_subtotal)}</strong></p>
      </section>

      <section className="card">
        <h2>Delivery address</h2>
        {data.addresses.length === 0 ? (
          <Empty>Save an address first (use the “Delivering to” button above).</Empty>
        ) : (
          <Field label="Deliver to">
            {({ id }) => (
              <select id={id} value={effectiveId ?? ""} onChange={(e) => chooseAddress(Number(e.target.value))}>
                {data.addresses.map((a) => (
                  <option key={a.id} value={a.id}>{a.label_display} — {shortAddress(a)}</option>
                ))}
              </select>
            )}
          </Field>
        )}
        <Button onClick={() => void getQuote()} disabled={effectiveId === null || quoting}>
          {quoting ? "Calculating…" : activeQuote ? "Recalculate delivery fee" : "Calculate delivery fee"}
        </Button>
        {quoteError && !quoteMessage && <Alert>{String(quoteError)}</Alert>}
        {quoteMessage && (
          <div role="alert" className="alert error">
            <p>{quoteMessage.message}</p>
            {quoteMessage.reasons.length > 0 && (
              <ul>
                {quoteMessage.reasons.map((r, i) => (
                  <li key={i}>{r.store_name ? `${r.store_name}: ` : ""}{r.message}</li>
                ))}
              </ul>
            )}
            {quoteMessage.retryable && <Button variant="secondary" onClick={() => void getQuote()}>Try again</Button>}
          </div>
        )}
      </section>

      {activeQuote && (
        <section className="card" aria-live="polite">
          <h2>Delivery fee</h2>
          <dl className="fee-breakdown">
            {activeQuote.legs.map((l) => (
              <div key={l.store_id}>
                <dt>{l.store_name} · {l.road_distance_km} km by road</dt>
                <dd>{money(l.delivery_fee)}</dd>
              </div>
            ))}
            <dt>Delivery before discount</dt><dd>{money(activeQuote.delivery_fee_before_discount)}</dd>
            {Number(activeQuote.delivery_discount) > 0 && (<><dt>Delivery discount</dt><dd>−{money(activeQuote.delivery_discount)}</dd></>)}
            <dt>You pay for delivery</dt><dd>{money(activeQuote.delivery_fee)}</dd>
            <dt>Order total</dt>
            <dd>{money(Number(data.cart.items_subtotal) + Number(activeQuote.delivery_fee))}</dd>
          </dl>
          <p className="muted">{activeQuote.distance_note} Fee is confirmed when you place the order.</p>
          <Field label="Notes for the store (optional)">
            {({ id }) => <textarea id={id} rows={2} maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} />}
          </Field>
          {placeError && <Alert>{placeError}</Alert>}
          <Button onClick={() => void place()} disabled={placing || data.cart.blocking_messages.length > 0}>
            {placing ? "Placing order…" : "Place order (cash on delivery)"}
          </Button>
        </section>
      )}
    </div>
  );
}
