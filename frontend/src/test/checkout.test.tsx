import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Checkout } from "../pages/customer/Checkout";
import { LocationProvider } from "../state/location";

const address = {
  id: 7, label: "HOME", label_display: "Home", recipient_name: "A", phone_number: "9", line1: "12 Market Rd",
  line2: "", landmark: "", city: "Kollam", district: "", state: "Kerala", postal_code: "691001", country: "IN",
  latitude: "8.8", longitude: "76.6", google_place_id: "", location_source: "MAP_PIN", location_confirmed: true,
  delivery_instructions: "", is_default: true,
};
const summary = {
  cart: { is_empty: false, items_subtotal: "300.00", blocking_messages: [], stores: [
    { store_id: 1, store_name: "Fresh Mart", items_subtotal: "300.00",
      items: [{ product_name: "Rice", quantity: 2, unit_price: "150.00", line_total: "300.00", is_available: true, warnings: [] }] },
  ] },
  addresses: [address], checkout_token: "tok-1", payment_methods: [],
};
const quote = {
  id: 55, address_id: 7, expires_at: "2099-01-01T00:00:00Z", delivery_fee_before_discount: "40.00",
  delivery_discount: "10.00", delivery_fee: "30.00", distance_note: "Distance is measured along roads using Google Maps.",
  legs: [{ store_id: 1, store_name: "Fresh Mart", items_subtotal: "300.00", road_distance_km: "3.2",
    delivery_fee_before_discount: "40.00", delivery_discount: "10.00", delivery_fee: "30.00" }],
};

function route(handlers: Record<string, () => { status: number; body: unknown }>) {
  const fn = vi.fn((url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url.replace("/api/v1", "")}`;
    const h = handlers[key];
    if (!h) throw new Error(`unexpected request ${key}`);
    const { status, body } = h();
    return Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(body) });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const renderIt = () =>
  render(
    <MemoryRouter>
      <LocationProvider><Checkout /></LocationProvider>
    </MemoryRouter>,
  );

afterEach(() => vi.unstubAllGlobals());

describe("Checkout", () => {
  it("shows the road distance and fee breakdown, and sends no price when ordering", async () => {
    const fn = route({
      "GET /customer/checkout/summary/": () => ({ status: 200, body: summary }),
      "POST /customer/delivery-quote/": () => ({ status: 201, body: quote }),
      "POST /customer/checkout/": () => ({ status: 201, body: { order_number: "ZV1" } }),
    });
    renderIt();
    await userEvent.click(await screen.findByRole("button", { name: /calculate delivery fee/i }));
    expect(await screen.findByText(/3\.2 km by road/)).toBeInTheDocument();
    expect(screen.getByText("−₹10.00")).toBeInTheDocument();
    expect(screen.getByText("₹330.00")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /place order/i }));
    await waitFor(() => expect(fn.mock.calls.some((c) => String(c[0]).endsWith("/customer/checkout/"))).toBe(true));
    const call = fn.mock.calls.find((c) => String(c[0]).endsWith("/customer/checkout/"))!;
    const body = JSON.parse((call[1] as { body: string }).body);
    expect(body).toEqual({ address_id: 7, quote_id: 55, checkout_token: "tok-1", customer_notes: "" });
    expect(JSON.stringify(body)).not.toMatch(/fee|total|payout/);
  });

  it("explains why a store can't deliver and offers retry for temporary errors", async () => {
    route({
      "GET /customer/checkout/summary/": () => ({ status: 200, body: summary }),
      "POST /customer/delivery-quote/": () => ({
        status: 422,
        body: { error: { code: "NOT_SERVICEABLE", message: "Some stores can't deliver to this address.", retryable: true,
          reasons: [{ store_id: 1, store_name: "Fresh Mart", code: "too_far", message: "This address is too far from the store." }] } },
      }),
    });
    renderIt();
    await userEvent.click(await screen.findByRole("button", { name: /calculate delivery fee/i }));
    expect(await screen.findByText(/Fresh Mart: This address is too far/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /place order/i })).not.toBeInTheDocument();
  });

  it("shows an empty-basket state", async () => {
    route({
      "GET /customer/checkout/summary/": () => ({ status: 200, body: { ...summary, cart: { ...summary.cart, is_empty: true, stores: [] } } }),
    });
    renderIt();
    expect(await screen.findByText(/basket is empty/i)).toBeInTheDocument();
  });

  it("shows a retryable load error", async () => {
    route({ "GET /customer/checkout/summary/": () => ({ status: 500, body: null }) });
    renderIt();
    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
