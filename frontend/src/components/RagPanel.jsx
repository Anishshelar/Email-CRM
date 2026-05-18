import { useEffect, useState } from "react";
import { api } from "../api/client";

function ScoreBar({ score }) {
  const pct = Math.round(score * 100);
  return (
    <div className="flex items-center gap-2 mt-1">
      <div className="flex-1 h-1 bg-gray-200 rounded-full overflow-hidden">
        <div className="h-full bg-accent-500 rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 w-10">{score.toFixed(3)}</span>
    </div>
  );
}

export function RagPanel({ subject, body }) {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const q = `${subject || ""} ${body || ""}`.trim().slice(0, 300);
    if (!q) return;
    setLoading(true);
    api.ragSearch(q, 3)
      .then((d) => setResults(d.results || []))
      .catch(() => setResults([]))
      .finally(() => setLoading(false));
  }, [open, subject, body]);

  return (
    <div className="card mt-4">
      <button
        className="w-full flex items-center justify-between px-4 py-3 text-left font-medium text-gray-800 hover:bg-gray-50 rounded-lg"
        onClick={() => setOpen((v) => !v)}
      >
        <span>Knowledge Base Matches</span>
        <span className="text-gray-400 text-sm">{open ? "Collapse" : "Expand"}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-gray-100 space-y-3 mt-3">
          {loading && <p className="text-sm text-gray-400 animate-pulse">Searching...</p>}
          {!loading && results.length === 0 && (
            <p className="text-sm text-gray-400">No matches found.</p>
          )}
          {results.map((r, i) => (
            <div key={i} className="text-sm">
              <div className="flex items-center gap-2">
                <span className="font-medium text-accent-700">{r.source_doc}</span>
                <span className="text-gray-400 text-xs">chunk #{r.chunk_index}</span>
              </div>
              <ScoreBar score={r.similarity_score} />
              <p className="mt-1 text-gray-600 text-xs line-clamp-3">{r.chunk_text}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
