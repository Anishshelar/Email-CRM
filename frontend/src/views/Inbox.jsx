import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { SentimentBadge } from "../components/SentimentBadge";
import { UrgencyBadge } from "../components/UrgencyBadge";
import { StatusBadge } from "../components/StatusBadge";

const TABS = [
  { label: "All",          filter: null },
  { label: "Needs Human",  filter: "Escalated" },
  { label: "Escalated",    filter: "Escalated" },
  { label: "Spam / Ignored", filter: "Ignored" },
];

const SORT_KEYS = ["timestamp", "priority_score", "sentiment_score", "urgency"];

const URGENCY_ORDER = { Critical: 4, High: 3, Medium: 2, Low: 1 };

function sortEmails(emails, key, asc) {
  return [...emails].sort((a, b) => {
    let va = a[key], vb = b[key];
    if (key === "urgency") {
      va = URGENCY_ORDER[va] ?? 0;
      vb = URGENCY_ORDER[vb] ?? 0;
    }
    if (va === null || va === undefined) return 1;
    if (vb === null || vb === undefined) return -1;
    if (va < vb) return asc ? -1 : 1;
    if (va > vb) return asc ? 1 : -1;
    return 0;
  });
}

function SortHeader({ label, sortKey, current, asc, onSort }) {
  const active = current === sortKey;
  return (
    <th
      className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide cursor-pointer select-none hover:text-gray-700"
      onClick={() => onSort(sortKey)}
    >
      {label}
      {active && <span className="ml-1 text-accent-500">{asc ? "▲" : "▼"}</span>}
    </th>
  );
}

export default function Inbox() {
  const [emails, setEmails]         = useState([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);
  const [tab, setTab]               = useState(0);
  const [sortKey, setSortKey]       = useState("timestamp");
  const [sortAsc, setSortAsc]       = useState(false);
  const [lastRefresh, setLastRefresh] = useState(null);
  const navigate = useNavigate();

  const fetchEmails = useCallback(() => {
    api.emails("?limit=200")
      .then((d) => {
        setEmails(d.emails || []);
        setLastRefresh(new Date());
        setError(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchEmails();
    const id = setInterval(fetchEmails, 10_000);
    return () => clearInterval(id);
  }, [fetchEmails]);

  const handleSort = (key) => {
    if (key === sortKey) setSortAsc((v) => !v);
    else { setSortKey(key); setSortAsc(false); }
  };

  const tabFilter = TABS[tab].filter;
  const needsHuman = tab === 1;

  let visible = emails;
  if (tab === 1) visible = emails.filter((e) => e.requires_human);
  else if (tabFilter) visible = emails.filter((e) => e.status === tabFilter);

  const sorted = sortEmails(visible, sortKey, sortAsc);

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-gray-900">Inbox</h1>
        <div className="flex items-center gap-3">
          {lastRefresh && (
            <span className="text-xs text-gray-400">
              Updated {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <button className="btn-secondary" onClick={fetchEmails}>Refresh</button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b border-gray-200">
        {TABS.map((t, i) => {
          const count = i === 0 ? emails.length
            : i === 1 ? emails.filter((e) => e.requires_human).length
            : emails.filter((e) => e.status === t.filter).length;
          return (
            <button
              key={i}
              onClick={() => setTab(i)}
              className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === i
                  ? "border-accent-600 text-accent-700"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {t.label}
              <span className={`ml-1.5 text-xs px-1.5 py-0.5 rounded-full ${
                tab === i ? "bg-accent-100 text-accent-700" : "bg-gray-100 text-gray-500"
              }`}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-2 rounded mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-gray-400 text-sm animate-pulse">Loading emails...</div>
      ) : sorted.length === 0 ? (
        <div className="text-gray-400 text-sm">No emails in this view.</div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <SortHeader label="Sender"    sortKey="sender"          current={sortKey} asc={sortAsc} onSort={handleSort} />
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Subject</th>
                <SortHeader label="Time"      sortKey="timestamp"       current={sortKey} asc={sortAsc} onSort={handleSort} />
                <SortHeader label="Priority"  sortKey="priority_score"  current={sortKey} asc={sortAsc} onSort={handleSort} />
                <SortHeader label="Sentiment" sortKey="sentiment_score" current={sortKey} asc={sortAsc} onSort={handleSort} />
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Category</th>
                <SortHeader label="Urgency"   sortKey="urgency"         current={sortKey} asc={sortAsc} onSort={handleSort} />
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {sorted.map((e) => (
                <tr
                  key={e.id}
                  className="hover:bg-gray-50 cursor-pointer"
                  onClick={() => navigate(`/thread/${e.id}`)}
                >
                  <td className="px-3 py-2.5 text-gray-800 font-medium max-w-[160px] truncate">
                    {e.sender}
                  </td>
                  <td className="px-3 py-2.5 text-gray-600 max-w-[240px] truncate">
                    {e.subject || <span className="text-gray-400">(no subject)</span>}
                  </td>
                  <td className="px-3 py-2.5 text-gray-500 whitespace-nowrap">
                    {new Date(e.timestamp).toLocaleString()}
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    {e.priority_score != null ? (
                      <span className={`font-semibold ${e.priority_score >= 80 ? "text-red-600" : e.priority_score >= 50 ? "text-orange-600" : "text-gray-600"}`}>
                        {e.priority_score}
                      </span>
                    ) : "—"}
                  </td>
                  <td className="px-3 py-2.5">
                    <SentimentBadge score={e.sentiment_score} />
                  </td>
                  <td className="px-3 py-2.5 text-gray-600">
                    {e.category || <span className="text-gray-400">—</span>}
                  </td>
                  <td className="px-3 py-2.5">
                    <UrgencyBadge urgency={e.urgency} />
                  </td>
                  <td className="px-3 py-2.5">
                    <StatusBadge status={e.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
