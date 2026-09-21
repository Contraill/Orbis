import type {
  ProviderStatus,
} from "../types";


export function formatDate(value: string | null) {
  if (!value) return "—";

  const normalized =
    /Z$|[+-]\d\d:\d\d$/.test(value)
      ? value
      : `${value}Z`;

  const date = new Date(normalized);

  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("tr-TR");
}


export function formatLatency(
  value: number | null,
) {
  if (value === null) return "—";

  return value < 1
    ? `${value.toFixed(2)} ms`
    : `${Math.round(value)} ms`;
}


export function StatusBadge({
  status,
}: {
  status: ProviderStatus;
}) {
  const labels: Record<ProviderStatus, string> = {
    unknown: "Unknown",
    healthy: "Healthy",
    degraded: "Degraded",
    circuit_open: "Circuit Open",
    disabled: "Disabled",
  };

  return (
    <span className={`status ${status}`}>
      {labels[status]}
    </span>
  );
}
