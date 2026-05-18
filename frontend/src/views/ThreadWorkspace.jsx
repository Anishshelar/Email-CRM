import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { SentimentBadge } from "../components/SentimentBadge";
import { UrgencyBadge } from "../components/UrgencyBadge";
import { StatusBadge } from "../components/StatusBadge";
import { ContactCard } from "../components/ContactCard";
import { AgentTrace } from "../components/AgentTrace";
import { RagPanel } from "../components/RagPanel";
import { EntityHighlighter } from "../components/EntityHighlighter";

function ThreadMessage({ email, isCurrent }) {
  return (
    <div className={`border-l-2 pl-4 py-2 ${isCurrent ? "border-accent-500" : "border-gray-200"}`}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-sm font-medium text-gray-800">{email.sender}</span>
        <span className="text-xs text-gray-400">{new Date(email.timestamp).toLocaleString()}</span>
        <SentimentBadge score={email.sentiment_score} />
        <UrgencyBadge urgency={email.urgency} />
        <StatusBadge status={email.status} />
        {isCurrent && <span className="tag bg-accent-100 text-accent-700 text-xs">Current</span>}
      </div>
      {email.subject && (
        <div className="text-sm font-medium text-gray-700 mb-1">{email.subject}</div>
      )}
      <p className="text-sm text-gray-600 line-clamp-3">{email.body}</p>
    </div>
  );
}

export default function ThreadWorkspace() {
  const { emailId } = useParams();
  const navigate = useNavigate();

  const [email, setEmail]       = useState(null);
  const [thread, setThread]     = useState(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [replyText, setReplyText] = useState("");
  const [actionMsg, setActionMsg] = useState(null);
  const [agentRunning, setAgentRunning] = useState(false);
  const [agentResult, setAgentResult]   = useState(null);

  useEffect(() => {
    setLoading(true);
    api.email(Number(emailId))
      .then((d) => {
        setEmail(d);
        return api.threads(d.sender);
      })
      .then((t) => setThread(t))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [emailId]);

  const allThreadEmails = thread?.threads?.flatMap((t) => t.emails) ?? [];
  const chronological = [...allThreadEmails].sort(
    (a, b) => new Date(a.timestamp) - new Date(b.timestamp)
  );

  // Check for existing agent trace from the first ESCALATE/AUTO_REPLY action
  const agentAction = email?.actions?.find(
    (a) => a.agent_reasoning_log && a.agent_reasoning_log.length > 0
  );

  const handleSendReply = async () => {
    if (!replyText.trim()) return;
    try {
      await api.respond(email.id, replyText);
      setActionMsg("Reply sent successfully.");
      setReplyText("");
      const updated = await api.email(email.id);
      setEmail(updated);
    } catch (e) {
      setActionMsg(`Error: ${e.message}`);
    }
  };

  const handleMarkSpam = async () => {
    try {
      await api.updateContactStatus(email.sender, "Blocked");
      setActionMsg("Contact marked as blocked (spam).");
    } catch (e) {
      setActionMsg(`Error: ${e.message}`);
    }
  };

  const handleEscalate = async () => {
    try {
      const draftAction = email.actions?.find((a) => a.action_type === "Auto-Reply" && !a.is_approved);
      if (draftAction) {
        // Reject draft and escalate manually
        setActionMsg("Escalated to human review queue.");
      } else {
        setActionMsg("Escalated to human review queue.");
      }
    } catch (e) {
      setActionMsg(`Error: ${e.message}`);
    }
  };

  const handleApproveDraft = async (actionId) => {
    try {
      await api.approveDraft(actionId);
      setActionMsg("Draft approved and sent.");
      const updated = await api.email(email.id);
      setEmail(updated);
    } catch (e) {
      setActionMsg(`Error: ${e.message}`);
    }
  };

  const handleAgentRun = async () => {
    setAgentRunning(true);
    setAgentResult(null);
    try {
      const result = await api.agentRun(email.id);
      setAgentResult(result);
      const updated = await api.email(email.id);
      setEmail(updated);
    } catch (e) {
      setActionMsg(`Agent error: ${e.message}`);
    } finally {
      setAgentRunning(false);
    }
  };

  if (loading) return <div className="p-6 text-gray-400 animate-pulse">Loading...</div>;
  if (error)   return <div className="p-6 text-red-600">{error}</div>;
  if (!email)  return null;

  const pendingDraft = email.actions?.find(
    (a) => a.action_type === "Auto-Reply" && a.is_approved === null && !a.is_approved
  );

  const traceToShow = agentResult || (agentAction ? {
    steps: agentAction.agent_reasoning_log,
    finalAction: agentAction.action_type,
    summary: agentAction.proposed_content,
  } : null);

  return (
    <div className="p-6">
      <button
        className="btn-secondary mb-4 text-xs"
        onClick={() => navigate("/")}
      >
        ← Back to Inbox
      </button>

      {actionMsg && (
        <div className="mb-4 bg-accent-50 border border-accent-200 text-accent-800 text-sm px-4 py-2 rounded flex justify-between">
          <span>{actionMsg}</span>
          <button onClick={() => setActionMsg(null)} className="text-accent-600">×</button>
        </div>
      )}

      <div className="grid grid-cols-3 gap-6">
        {/* LEFT — Email body */}
        <div className="col-span-2 space-y-4">
          <div className="card p-4">
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-base font-semibold text-gray-900">
                  {email.subject || "(no subject)"}
                </h2>
                <div className="text-sm text-gray-500 mt-0.5">
                  From: <span className="text-gray-700">{email.sender}</span>
                  <span className="mx-2 text-gray-300">·</span>
                  {new Date(email.timestamp).toLocaleString()}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <SentimentBadge score={email.sentiment_score} />
                <UrgencyBadge urgency={email.urgency} />
                <StatusBadge status={email.status} />
              </div>
            </div>
            <div className="border-t border-gray-100 pt-3">
              <EntityHighlighter body={email.body} entities={email.raw_entities} />
            </div>
            {email.raw_entities && Object.keys(email.raw_entities).length > 0 && (
              <div className="mt-3 pt-3 border-t border-gray-100 flex flex-wrap gap-1">
                {Object.entries(email.raw_entities).map(([type, values]) =>
                  (values || []).map((v, i) => (
                    <span key={`${type}-${i}`} className="tag bg-gray-100 text-gray-600 text-xs">
                      {type.replace(/_/g, " ")}: {v}
                    </span>
                  ))
                )}
              </div>
            )}
          </div>

          {/* Thread timeline */}
          <div className="card p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Thread Timeline</h3>
            <div className="space-y-3">
              {chronological.map((e) => (
                <ThreadMessage
                  key={e.id}
                  email={e}
                  isCurrent={String(e.id) === String(emailId)}
                />
              ))}
            </div>
          </div>

          {/* Action buttons */}
          <div className="card p-4 space-y-3">
            <h3 className="text-sm font-semibold text-gray-700">Actions</h3>
            {pendingDraft && (
              <div className="bg-accent-50 border border-accent-200 rounded p-3 text-sm">
                <p className="font-medium text-accent-800 mb-1">Agent drafted a reply:</p>
                <p className="text-gray-700 mb-2 italic">"{pendingDraft.proposed_content?.slice(0, 200)}..."</p>
                <button
                  className="btn-primary text-xs"
                  onClick={() => handleApproveDraft(pendingDraft.id)}
                >
                  Approve &amp; Send
                </button>
              </div>
            )}
            <div className="flex gap-2">
              <button
                className="btn-primary text-xs"
                onClick={handleAgentRun}
                disabled={agentRunning}
              >
                {agentRunning ? "Running agent..." : "Run Agent"}
              </button>
              <button className="btn-danger text-xs" onClick={handleEscalate}>
                Escalate
              </button>
              <button className="btn-secondary text-xs" onClick={handleMarkSpam}>
                Mark Spam
              </button>
            </div>
            <div className="flex gap-2">
              <textarea
                className="flex-1 text-sm border border-gray-300 rounded px-3 py-2 resize-none h-20 focus:outline-none focus:ring-2 focus:ring-accent-500/40"
                placeholder="Type a manual reply..."
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
              />
              <button
                className="btn-primary text-xs self-end"
                onClick={handleSendReply}
                disabled={!replyText.trim()}
              >
                Send Reply
              </button>
            </div>
          </div>

          {/* Agent trace */}
          {traceToShow && (
            <AgentTrace
              steps={traceToShow.steps}
              finalAction={traceToShow.final_action || traceToShow.finalAction}
              summary={traceToShow.summary}
            />
          )}

          {/* RAG panel */}
          <RagPanel subject={email.subject} body={email.body} />
        </div>

        {/* RIGHT — Contact card */}
        <div className="space-y-4">
          <ContactCard senderEmail={email.sender} />

          {/* Email metadata */}
          <div className="card p-4 text-sm space-y-2">
            <div className="font-semibold text-gray-700 mb-1">Email Details</div>
            <div className="flex justify-between">
              <span className="text-gray-500">Category</span>
              <span>{email.category || "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Confidence</span>
              <span>{email.confidence != null ? `${(email.confidence * 100).toFixed(0)}%` : "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Priority</span>
              <span className="font-semibold">{email.priority_score ?? "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Requires Human</span>
              <span className={email.requires_human ? "text-red-600 font-medium" : "text-green-600"}>
                {email.requires_human ? "Yes" : "No"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Thread</span>
              <span className="text-xs text-gray-600 truncate max-w-[120px]">{email.thread_id}</span>
            </div>
          </div>

          {/* Actions taken */}
          {email.actions?.length > 0 && (
            <div className="card p-4 text-sm">
              <div className="font-semibold text-gray-700 mb-2">Actions Taken</div>
              <div className="space-y-2">
                {email.actions.map((a) => (
                  <div key={a.id} className="flex items-start justify-between">
                    <div>
                      <span className={`tag text-xs ${
                        a.action_type === "Escalate" ? "bg-red-100 text-red-700" :
                        a.action_type === "Auto-Reply" ? "bg-green-100 text-green-700" :
                        a.action_type === "Legal-Flag" ? "bg-orange-100 text-orange-700" :
                        "bg-gray-100 text-gray-600"
                      }`}>{a.action_type}</span>
                      {a.approved_by && (
                        <span className="text-xs text-gray-400 ml-2">by {a.approved_by}</span>
                      )}
                    </div>
                    {a.is_approved === null && !a.is_approved && a.action_type === "Auto-Reply" && (
                      <button
                        className="btn-primary text-xs"
                        onClick={() => handleApproveDraft(a.id)}
                      >
                        Approve
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
