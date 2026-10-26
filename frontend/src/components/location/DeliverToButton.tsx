import { useSelectedLocation } from "../../state/location";

/** Header control: "Delivering to / Home · 12 Market Rd / Change location". */
export function DeliverToButton() {
  const { selected, openDialog } = useSelectedLocation();
  return (
    <button type="button" className="deliver-to" onClick={openDialog} aria-haspopup="dialog">
      <small>Delivering to</small>
      <strong>{selected ? `${selected.label} · ${selected.title}` : "Choose your location"}</strong>
      <small>Change location</small>
    </button>
  );
}
