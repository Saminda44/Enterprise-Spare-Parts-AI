import { useEffect, useRef, useState } from "react";
import { Loader2, CheckCircle2, AlertTriangle, X } from "lucide-react";
import { fetchRefreshStatus, type RefreshStatus } from "../api/client";

// The API re-runs the affected pipeline stages when a source workbook changes
// (src/refresh.py). This banner says so while it happens, and offers a reload once the
// new numbers are published.

const POLL_MS = 5000;

export function RefreshBanner() {
  const [status, setStatus] = useState<RefreshStatus | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const seenFinish = useRef<string | null>(null);
  const [finishedHere, setFinishedHere] = useState(false);

  useEffect(() => {
    let alive = true;
    const tick = () => fetchRefreshStatus()
      .then(s => {
        if (!alive) return;
        setStatus(s);
        // Offer a reload only for a refresh that finished while this page was open.
        if (s.finished_at && seenFinish.current !== null && s.finished_at !== seenFinish.current) {
          setFinishedHere(true);
        }
        if (seenFinish.current === null) seenFinish.current = s.finished_at ?? "";
        else if (s.finished_at) seenFinish.current = s.finished_at;
      })
      .catch(() => { /* API restarting; try again next tick */ });
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (!status) return null;
  const busy = status.state === "checking" || status.state === "running";
  const waiting = (status.waiting_for?.length ?? 0) > 0;
  const failed = status.state === "failed" && dismissed !== status.finished_at;
  const done = finishedHere && status.state === "done" && dismissed !== status.finished_at;

  if (!busy && !waiting && !failed && !done) return null;

  const changed = (status.changed ?? []).join(", ");
  let body: React.ReactNode;
  let tone = "bg-blue-50 border-blue-200 text-blue-800";
  if (waiting && !busy) {
    body = <><Loader2 size={14} className="animate-spin" /> {status.waiting_for!.join(", ")} changed — waiting for the file to finish saving…</>;
  } else if (status.state === "checking") {
    body = <><Loader2 size={14} className="animate-spin" /> Checking source files for changes…</>;
  } else if (status.state === "running") {
    body = <>
      <Loader2 size={14} className="animate-spin" />
      Updating analysis from <b>{changed}</b>
      {status.stage && <> — step <b>{status.stage}</b> ({status.position}/{status.total})</>}
    </>;
  } else if (failed) {
    tone = "bg-red-50 border-red-200 text-red-800";
    body = <><AlertTriangle size={14} /> Analysis update failed: {status.error}</>;
  } else {
    tone = "bg-emerald-50 border-emerald-200 text-emerald-800";
    body = <>
      <CheckCircle2 size={14} /> Analysis updated from <b>{changed || "source files"}</b>.
      <button onClick={() => window.location.reload()}
        className="ml-2 rounded-md bg-emerald-600 text-white px-2.5 py-0.5 text-xs font-medium hover:opacity-90">
        Reload to see the new numbers
      </button>
    </>;
  }

  return (
    <div className={`flex items-center gap-2 border-b px-6 py-2 text-sm ${tone}`}>
      {body}
      {(failed || done) && (
        <button onClick={() => setDismissed(status.finished_at ?? "")}
          className="ml-auto opacity-60 hover:opacity-100" title="Dismiss">
          <X size={14} />
        </button>
      )}
    </div>
  );
}
