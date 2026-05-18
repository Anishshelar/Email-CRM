const STYLES = {
  Replied:    "bg-green-100 text-green-700",
  Escalated:  "bg-red-100 text-red-700",
  Processing: "bg-accent-100 text-accent-700",
  Received:   "bg-gray-100 text-gray-600",
  Ignored:    "bg-gray-100 text-gray-400",
};

export function StatusBadge({ status }) {
  return (
    <span className={`tag ${STYLES[status] || "bg-gray-100 text-gray-500"}`}>
      {status}
    </span>
  );
}
