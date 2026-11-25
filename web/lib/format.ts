export function formatDate(value: string | number | null | undefined): string {
  if (!value) return "—";
  // SQLite CURRENT_TIMESTAMP is UTC but omits its time zone suffix.
  const normalized =
    typeof value === "string" ? value.replace(" ", "T") : value;
  const timestamp =
    typeof normalized === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(normalized)
      ? `${normalized}Z`
      : normalized;
  const date =
    typeof timestamp === "number"
      ? new Date(timestamp * 1000)
      : new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value);
}
