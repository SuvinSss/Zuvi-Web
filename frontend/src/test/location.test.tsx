import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockMapsLibrary, placesLib } from "./mapsMock";

vi.mock("@vis.gl/react-google-maps", () => mockMapsLibrary());

import { AddressSearch } from "../components/maps/AddressSearch";
import { LocationPicker } from "../components/maps/LocationPicker";
import { CurrentLocationButton } from "../components/location/CurrentLocationButton";
import { DeliverToButton } from "../components/location/DeliverToButton";
import { LocationProvider } from "../state/location";
import * as maps from "../state/maps";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

function geolocation(impl: (ok: PositionCallback, fail: PositionErrorCallback) => void) {
  Object.defineProperty(navigator, "geolocation", {
    configurable: true,
    value: { getCurrentPosition: impl },
  });
}

describe("CurrentLocationButton", () => {
  it("explains a denied permission and offers search instead", async () => {
    geolocation((_ok, fail) => fail({ code: 1 } as GeolocationPositionError));
    const onLocate = vi.fn();
    render(<CurrentLocationButton onLocate={onLocate} />);
    await userEvent.click(screen.getByRole("button", { name: /current location/i }));
    expect(await screen.findByText(/permission was denied/i)).toBeInTheDocument();
    expect(onLocate).not.toHaveBeenCalled();
  });

  it("explains a timeout", async () => {
    geolocation((_ok, fail) => fail({ code: 3 } as GeolocationPositionError));
    render(<CurrentLocationButton onLocate={vi.fn()} />);
    await userEvent.click(screen.getByRole("button"));
    expect(await screen.findByText(/took too long/i)).toBeInTheDocument();
  });

  it("warns when accuracy is poor but still passes the point on for correction", async () => {
    geolocation((ok) => ok({ coords: { latitude: 8.8, longitude: 76.6, accuracy: 900 } } as GeolocationPosition));
    const onLocate = vi.fn();
    render(<CurrentLocationButton onLocate={onLocate} />);
    await userEvent.click(screen.getByRole("button"));
    expect(await screen.findByText(/accurate to about 900 m/i)).toBeInTheDocument();
    expect(onLocate).toHaveBeenCalledWith({ lat: 8.8, lng: 76.6 }, 900);
  });
});

describe("AddressSearch", () => {
  it("shows suggestions and returns the chosen place with its coordinates", async () => {
    const place = {
      id: "ChIJabcdefghij",
      formattedAddress: "12 Market Road, Kollam, Kerala 691001, India",
      location: { lat: () => 8.8932, lng: () => 76.6141 },
      addressComponents: [
        { longText: "12", types: ["street_number"] },
        { longText: "Market Road", types: ["route"] },
        { longText: "Kollam", types: ["locality"] },
        { longText: "Kerala", types: ["administrative_area_level_1"] },
        { longText: "691001", types: ["postal_code"] },
      ],
      fetchFields: vi.fn().mockResolvedValue(undefined),
    };
    placesLib.AutocompleteSuggestion.fetchAutocompleteSuggestions.mockResolvedValue({
      suggestions: [{ placePrediction: { text: { text: "12 Market Road, Kollam" }, toPlace: () => place } }],
    });
    const onSelect = vi.fn();
    render(<AddressSearch onSelect={onSelect} />);
    await userEvent.type(screen.getByRole("combobox"), "12 Market");
    await userEvent.click(await screen.findByRole("button", { name: "12 Market Road, Kollam" }, { timeout: 2000 }));
    await waitFor(() => expect(onSelect).toHaveBeenCalled());
    const arg = onSelect.mock.calls[0]![0];
    expect(arg.point).toEqual({ lat: 8.8932, lng: 76.6141 });
    expect(arg.address.line1).toBe("12 Market Road");
    expect(arg.address.postalCode).toBe("691001");
    expect(arg.address.precise).toBe(true);
    const call = placesLib.AutocompleteSuggestion.fetchAutocompleteSuggestions.mock.calls[0]![0];
    expect(call.sessionToken).toBeDefined();
    expect(call.includedRegionCodes).toEqual(["in"]);
  });

  it("shows a friendly message when Google search fails", async () => {
    placesLib.AutocompleteSuggestion.fetchAutocompleteSuggestions.mockRejectedValue(new Error("boom"));
    render(<AddressSearch onSelect={vi.fn()} />);
    await userEvent.type(screen.getByRole("combobox"), "market");
    expect(await screen.findByRole("alert", {}, { timeout: 2000 })).toHaveTextContent(/isn't working right now/i);
  });
});

describe("LocationPicker", () => {
  beforeEach(() => {
    vi.spyOn(maps, "useMapsAvailability").mockReturnValue({ status: "ready", mapId: "m" });
  });

  it("reverse geocodes a corrected pin through the backend", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          formatted_address: "Corrected Rd, Kollam",
          place_id: "ChIJcorrected01",
          latitude: "8.820000",
          longitude: "76.680000",
          precise: true,
          components: { line1: "Corrected Rd", locality: "Kollam", district: "", state: "Kerala", postal_code: "691001" },
        }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const onChange = vi.fn();
    render(<LocationPicker point={{ lat: 8.81, lng: 76.66 }} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: /marker/ })); // drag end
    expect(onChange).toHaveBeenCalledWith({ lat: 8.82, lng: 76.68 }, null);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled(), { timeout: 2000 });
    const body = JSON.parse((fetchMock.mock.calls[0]![1] as { body: string }).body);
    expect(body).toEqual({ latitude: "8.820000", longitude: "76.680000" });
    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith(
        { lat: 8.82, lng: 76.68 },
        expect.objectContaining({ line1: "Corrected Rd", precise: true }),
      ),
    );
  });

  it("keeps the pin and says so when the address lookup fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: () => Promise.resolve({ error: { code: "MAPS_UNAVAILABLE", message: "down", retryable: true } }),
      }),
    );
    render(<LocationPicker point={null} onChange={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "tap map" }));
    expect(await screen.findByText(/couldn't find an address for this pin/i, {}, { timeout: 2000 })).toBeInTheDocument();
  });

  it("asks anonymous visitors to sign in rather than showing an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ error: { code: "NOT_AUTHENTICATED", message: "Sign in" } }),
      }),
    );
    render(<LocationPicker point={null} onChange={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "tap map" }));
    expect(await screen.findByText(/sign in to look up/i, {}, { timeout: 2000 })).toBeInTheDocument();
  });

  it("falls back to a message, not a broken map, when Maps is unconfigured", () => {
    vi.spyOn(maps, "useMapsAvailability").mockReturnValue({ status: "unconfigured" });
    render(<LocationPicker point={null} onChange={vi.fn()} />);
    expect(screen.queryByTestId("fake-map")).not.toBeInTheDocument();
    expect(screen.getByText(/maps aren't available/i)).toBeInTheDocument();
  });

  it("explains a rejected key", () => {
    vi.spyOn(maps, "useMapsAvailability").mockReturnValue({ status: "rejected" });
    render(<LocationPicker point={null} onChange={vi.fn()} />);
    expect(screen.getByText(/rejected this site's key/i)).toBeInTheDocument();
  });
});

describe("DeliverToButton", () => {
  it("shows the prompt when nothing is selected", () => {
    render(<LocationProvider><DeliverToButton /></LocationProvider>);
    expect(screen.getByText("Delivering to")).toBeInTheDocument();
    expect(screen.getByText("Choose your location")).toBeInTheDocument();
  });

  it("restores the saved selection and ignores corrupt storage", () => {
    window.localStorage.setItem(
      "zuuvi.selectedLocation.v1",
      JSON.stringify({ label: "Home", title: "12 Market Rd", point: { lat: 8.8, lng: 76.6 }, addressId: 3 }),
    );
    const { unmount } = render(<LocationProvider><DeliverToButton /></LocationProvider>);
    expect(screen.getByText("Home · 12 Market Rd")).toBeInTheDocument();
    unmount();
    window.localStorage.setItem("zuuvi.selectedLocation.v1", "{not json");
    render(<LocationProvider><DeliverToButton /></LocationProvider>);
    expect(screen.getByText("Choose your location")).toBeInTheDocument();
  });
});
