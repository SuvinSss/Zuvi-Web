import type { ReactNode } from "react";
import { vi } from "vitest";

export const placesLib = {
  AutocompleteSessionToken: class {},
  AutocompleteSuggestion: { fetchAutocompleteSuggestions: vi.fn() },
};

/** Replace the Google Maps React bindings with simple, clickable stand-ins. */
export function mockMapsLibrary(placesReady = true) {
  return {
    APIProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
    useMapsLibrary: () => (placesReady ? placesLib : null),
    Map: ({
      children,
      onClick,
    }: {
      children?: ReactNode;
      onClick?: (e: { detail: { latLng: { lat: number; lng: number } } }) => void;
    }) => (
      <div data-testid="fake-map">
        <button type="button" onClick={() => onClick?.({ detail: { latLng: { lat: 8.8139, lng: 76.6672 } } })}>
          tap map
        </button>
        {children}
      </div>
    ),
    AdvancedMarker: ({
      onDragEnd,
      title,
    }: {
      onDragEnd?: (e: { latLng: { lat: () => number; lng: () => number } }) => void;
      title?: string;
    }) => (
      <button
        type="button"
        onClick={() => onDragEnd?.({ latLng: { lat: () => 8.82, lng: () => 76.68 } })}
      >
        {`marker:${title ?? ""}`}
      </button>
    ),
  };
}
