const STYLES = {
  Critical: "bg-red-100 text-red-700",
  High:     "bg-orange-100 text-orange-700",
  Medium:   "bg-yellow-100 text-yellow-700",
  Low:      "bg-gray-100 text-gray-500",
};

export function UrgencyBadge({ urgency }) {
  if (!urgency) return <span className="tag bg-gray-100 text-gray-400">—</span>;
  return <span className={`tag ${STYLES[urgency] || "bg-gray-100 text-gray-500"}`}>{urgency}</span>;
}
