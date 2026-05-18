import { useState } from "react";

function StepRow({ step }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-gray-200 rounded mb-1 text-sm">
      <button
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="flex-none w-5 h-5 rounded-full bg-accent-100 text-accent-700 text-xs font-semibold flex items-center justify-center">
          {step.step}
        </span>
        <span className="font-medium text-gray-700">{step.action}</span>
        <span className="ml-auto text-gray-400 text-xs">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 border-t border-gray-100">
          <div>
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Thought</span>
            <p className="mt-0.5 text-gray-700">{step.thought}</p>
          </div>
          <div>
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Input</span>
            <pre className="mt-0.5 text-xs bg-gray-50 rounded p-2 overflow-x-auto text-gray-600">
              {JSON.stringify(step.action_input, null, 2)}
            </pre>
          </div>
          <div>
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Observation</span>
            <p className="mt-0.5 text-gray-600 text-xs">{step.observation}</p>
          </div>
        </div>
      )}
    </div>
  );
}

export function AgentTrace({ steps, finalAction, summary }) {
  const [open, setOpen] = useState(false);
  if (!steps || steps.length === 0) return null;

  return (
    <div className="card mt-4">
      <button
        className="w-full flex items-center justify-between px-4 py-3 text-left font-medium text-gray-800 hover:bg-gray-50 rounded-lg"
        onClick={() => setOpen((v) => !v)}
      >
        <span>Agent Reasoning Trace ({steps.length} steps)</span>
        <span className="text-gray-400 text-sm">{open ? "Collapse" : "Expand"}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-gray-100">
          <div className="mt-3 space-y-0.5">
            {steps.map((s) => (
              <StepRow key={s.step} step={s} />
            ))}
          </div>
          <div className="mt-3 pt-3 border-t border-gray-100">
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Final Action</span>
            <p className="mt-0.5 font-medium text-accent-700">{finalAction}</p>
            {summary && <p className="mt-1 text-sm text-gray-600">{summary}</p>}
          </div>
        </div>
      )}
    </div>
  );
}
