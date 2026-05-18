// Highlights extracted entities in email body text.
// Each entity type gets a distinct background colour.

const CATEGORY_COLORS = {
  order_ids:        "bg-blue-100 text-blue-800",
  ticket_ids:       "bg-purple-100 text-purple-800",
  monetary_amounts: "bg-green-100 text-green-800",
  deadlines:        "bg-orange-100 text-orange-800",
  products_mentioned: "bg-accent-100 text-accent-800",
};

function buildHighlightMap(entities) {
  const map = new Map();
  if (!entities) return map;
  for (const [type, values] of Object.entries(entities)) {
    for (const v of values || []) {
      map.set(String(v), CATEGORY_COLORS[type] || "bg-yellow-100 text-yellow-800");
    }
  }
  return map;
}

export function EntityHighlighter({ body, entities }) {
  if (!body) return null;
  const map = buildHighlightMap(entities);
  if (map.size === 0) {
    return (
      <pre className="whitespace-pre-wrap text-sm text-gray-700 font-sans leading-relaxed">
        {body}
      </pre>
    );
  }

  // Simple replace: sort by length desc to avoid partial matches
  const terms = [...map.keys()].sort((a, b) => b.length - a.length);
  const escaped = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const regex = new RegExp(`(${escaped.join("|")})`, "g");

  const parts = body.split(regex);
  return (
    <pre className="whitespace-pre-wrap text-sm text-gray-700 font-sans leading-relaxed">
      {parts.map((part, i) => {
        const color = map.get(part);
        if (color) {
          return (
            <mark key={i} className={`rounded px-0.5 ${color} not-italic font-medium`}>
              {part}
            </mark>
          );
        }
        return part;
      })}
    </pre>
  );
}
