import { useEffect, useState } from "react";
import { api } from "../api/client";

const STATUS_STYLE = {
  VIP:     "bg-accent-100 text-accent-700",
  Active:  "bg-green-100 text-green-700",
  Churned: "bg-red-100 text-red-700",
  Blocked: "bg-gray-200 text-gray-600",
};

function RiskBar({ score }) {
  if (score === null || score === undefined) return <span className="text-gray-400 text-xs">N/A</span>;
  const pct = Math.round(score * 100);
  const color = score >= 0.7 ? "bg-red-500" : score >= 0.4 ? "bg-yellow-500" : "bg-green-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-600 w-8">{pct}%</span>
    </div>
  );
}

export function ContactCard({ senderEmail }) {
  const [contact, setContact] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!senderEmail) return;
    api.contact(senderEmail)
      .then(setContact)
      .catch((e) => setErr(e.message));
  }, [senderEmail]);

  if (err) return <div className="card p-4 text-sm text-gray-500">Contact not found</div>;
  if (!contact) return <div className="card p-4 text-sm text-gray-400 animate-pulse">Loading contact...</div>;

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-semibold text-gray-900">{contact.name || contact.email}</div>
          {contact.company && <div className="text-sm text-gray-500">{contact.company}</div>}
          <div className="text-xs text-gray-400 mt-0.5">{contact.email}</div>
        </div>
        <span className={`tag text-xs ${STATUS_STYLE[contact.status] || "bg-gray-100 text-gray-500"}`}>
          {contact.status}
        </span>
      </div>

      {contact.account_value != null && (
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">Account Value</span>
          <span className="font-medium text-gray-800">${contact.account_value.toLocaleString()}/mo</span>
        </div>
      )}

      <div>
        <div className="flex justify-between text-sm mb-1">
          <span className="text-gray-500">Churn Risk</span>
        </div>
        <RiskBar score={contact.churn_risk_score} />
      </div>

      {contact.last_contact_at && (
        <div className="text-xs text-gray-400">
          Last contact: {new Date(contact.last_contact_at).toLocaleDateString()}
        </div>
      )}
    </div>
  );
}
