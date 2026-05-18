import { useEffect, useState } from "react";
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine
} from "recharts";
import { api } from "../api/client";

// ── Sentiment trend chart ──────────────────────────────────────────────────────

function SentimentTrend() {
  const [sender, setSender] = useState("");
  const [days, setDays]     = useState(30);
  const [data, setData]     = useState(null);
  const [error, setError]   = useState(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    if (!sender.trim()) return;
    setLoading(true);
    api.sentimentTrend(sender, days)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  const chartData = data?.data_points.map((p, i) => ({
    name: new Date(p.timestamp).toLocaleDateString(),
    score: p.sentiment_score,
    ma: data.moving_average[i],
  })) ?? [];

  return (
    <div className="card p-5">
      <h2 className="text-base font-semibold text-gray-800 mb-3">Sentiment Trend</h2>
      <div className="flex gap-2 mb-4">
        <input
          type="email"
          className="flex-1 text-sm border border-gray-300 rounded px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-accent-500/40"
          placeholder="Sender email..."
          value={sender}
          onChange={(e) => setSender(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
        />
        <select
          className="text-sm border border-gray-300 rounded px-2 py-1.5"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        >
          <option value={7}>7 days</option>
          <option value={30}>30 days</option>
          <option value={90}>90 days</option>
        </select>
        <button className="btn-primary text-xs" onClick={load}>Load</button>
      </div>

      {error && <p className="text-red-500 text-sm">{error}</p>}
      {loading && <p className="text-gray-400 text-sm animate-pulse">Loading...</p>}

      {data && !loading && (
        <>
          {data.escalation_alert && (
            <div className="mb-3 bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2 rounded">
              Escalation alert: {data.consecutive_negative_count} consecutive negative emails
            </div>
          )}
          {chartData.length === 0 ? (
            <p className="text-gray-400 text-sm">No classified emails found for this sender.</p>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis domain={[-1, 1]} tick={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 6 }}
                  formatter={(v, name) => [v.toFixed(3), name === "score" ? "Sentiment" : "3-pt MA"]}
                />
                <ReferenceLine y={0} stroke="#9ca3af" strokeDasharray="3 3" />
                <Line type="monotone" dataKey="score" stroke="#3b82f6" dot={{ r: 3 }} strokeWidth={1.5} name="score" />
                <Line type="monotone" dataKey="ma"    stroke="#f97316" dot={false} strokeWidth={2} strokeDasharray="4 2" name="ma" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </>
      )}
    </div>
  );
}

// ── Category breakdown chart ───────────────────────────────────────────────────

function CategoryBreakdown() {
  const [data, setData]   = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.categoryBreakdown()
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  const chartData = data?.breakdown ?? [];

  return (
    <div className="card p-5">
      <h2 className="text-base font-semibold text-gray-800 mb-3">Category Breakdown</h2>
      {error && <p className="text-red-500 text-sm">{error}</p>}
      {!data && !error && <p className="text-gray-400 text-sm animate-pulse">Loading...</p>}
      {chartData.length === 0 && data && (
        <p className="text-gray-400 text-sm">No categorized emails yet.</p>
      )}
      {chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 20, left: -20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis
              dataKey="category"
              tick={{ fontSize: 11 }}
              angle={-30}
              textAnchor="end"
              interval={0}
            />
            <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={{ fontSize: 12, borderRadius: 6 }} />
            <Bar dataKey="count" fill="#3b82f6" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── At-risk accounts ───────────────────────────────────────────────────────────

function AtRiskAccounts() {
  const [data, setData]   = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.dashboardStats()
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  const contacts = data?.at_risk_contacts ?? [];

  return (
    <div className="card p-5">
      <h2 className="text-base font-semibold text-gray-800 mb-3">
        At-Risk Accounts
        <span className="ml-2 text-xs font-normal text-gray-400">(churn risk &gt; 70%)</span>
      </h2>
      {error && <p className="text-red-500 text-sm">{error}</p>}
      {!data && !error && <p className="text-gray-400 text-sm animate-pulse">Loading...</p>}
      {data && contacts.length === 0 && (
        <p className="text-gray-400 text-sm">No high-risk contacts found.</p>
      )}
      {contacts.length > 0 && (
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-200">
                <th className="pb-2 pr-3">Contact</th>
                <th className="pb-2 pr-3">Company</th>
                <th className="pb-2 pr-3">Account Value</th>
                <th className="pb-2">Churn Risk</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {contacts.map((c) => {
                const pct = Math.round((c.churn_risk_score || 0) * 100);
                return (
                  <tr key={c.email} className="hover:bg-gray-50">
                    <td className="py-2 pr-3">
                      <div className="font-medium text-gray-800">{c.name || c.email}</div>
                      <div className="text-xs text-gray-400">{c.name ? c.email : ""}</div>
                    </td>
                    <td className="py-2 pr-3 text-gray-600">{c.company || "—"}</td>
                    <td className="py-2 pr-3 font-medium text-gray-800">
                      {c.account_value != null ? `$${c.account_value.toLocaleString()}/mo` : "—"}
                    </td>
                    <td className="py-2">
                      <div className="flex items-center gap-2">
                        <div className="w-24 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${pct >= 70 ? "bg-red-500" : "bg-yellow-500"}`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className={`text-xs font-semibold ${pct >= 70 ? "text-red-600" : "text-yellow-600"}`}>
                          {pct}%
                        </span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function Analytics() {
  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-semibold text-gray-900">Analytics</h1>
      <div className="grid grid-cols-2 gap-6">
        <CategoryBreakdown />
        <AtRiskAccounts />
      </div>
      <SentimentTrend />
    </div>
  );
}
