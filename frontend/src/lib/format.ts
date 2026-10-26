const rupee = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
});

export const money = (value: string | number | null | undefined): string =>
  value === null || value === undefined || value === "" ? "—" : rupee.format(Number(value));

export function parsePoint(lat: string | null | undefined, lng: string | null | undefined) {
  if (lat == null || lng == null || lat === "" || lng === "") return null;
  const a = Number(lat);
  const b = Number(lng);
  return Number.isFinite(a) && Number.isFinite(b) ? { lat: a, lng: b } : null;
}

export function toFixed6(n: number): string {
  return n.toFixed(6);
}

export function shortAddress(a: { line1: string; city: string }): string {
  return [a.line1, a.city].filter(Boolean).join(", ");
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

export function minutes(seconds: number): number {
  return Math.max(1, Math.round(seconds / 60));
}
