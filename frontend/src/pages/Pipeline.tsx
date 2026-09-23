import { useEffect, useRef, useState, useCallback } from "react";
import { api } from "../api/client";
import {
  Play, CheckCircle2, XCircle, Clock, Loader2,
  ChevronDown, ChevronUp, Trash2, RefreshCw, Terminal,
} from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────────

interface StageInfo {
  stage: string;
  name: string;
}

interface ModuleInfo {
  module: number;
  name: string;
}

interface PipelineStatusMap {
  [key: string]: boolean;
}

interface Job {
  job_id: string;
  kind: "stage" | "module";
  name: string;
  status: "PENDING" | "RUNNING" | "SUCCESS" | "FAILED";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  logs: string;
  error: string | null;
  params?: Record<string, unknown>;
}

// ── API helpers ────────────────────────────────────────────────────────────────

const fetchStages = () =>
  api.get<{ stages: StageInfo[]; pipeline_status: PipelineStatusMap; pipeline_freshness: Record<string, string | null> }>
    ("/pipeline/stages").then(r => r.data);

const fetchModules = () =>
  api.get<{ modules: ModuleInfo[] }>("/pipeline/modules").then(r => r.data);

const fetchJobs = () =>
  api.get<{ total: number; jobs: Job[] }>("/pipeline/jobs?limit=30").then(r => r.data);

const fetchJob = (jobId: string) =>
  api.get<Job>(`/pipeline/jobs/${jobId}`).then(r => r.data);

const runStage = (stage: string, refresh: boolean) =>
  api.post<{ job_id: string; name: string; status: string }>(`/pipeline/stages/${stage}`, { refresh }).then(r => r.data);

const runModule = (module: number, save: boolean) =>
  api.post<{ job_id: string; name: string; status: string }>(`/pipeline/modules/${module}`, { save }).then(r => r.data);

const clearJobs = () => api.delete("/pipeline/jobs");
const clearApiCache = () => api.post("/cache/clear").catch(() => null);

// ── Helpers ────────────────────────────────────────────────────────────────────

function elapsed(job: Job): string {
  if (!job.started_at) return "—";
  const end = job.finished_at ? new Date(job.finished_at) : new Date();
  const ms = end.getTime() - new Date(job.started_at).getTime();
  return ms < 60_000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.floor(ms / 60_000)}m ${Math.floor((ms % 60_000) / 1000)}s`;
}

function timeAgo(iso: string): string {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: Job["status"] }) {
  const cfg = {
    PENDING:  { icon: <Clock size={12}/>,                        cls: "bg-slate-100 text-slate-500" },
    RUNNING:  { icon: <Loader2 size={12} className="animate-spin"/>, cls: "bg-blue-50 text-blue-600" },
    SUCCESS:  { icon: <CheckCircle2 size={12}/>,                 cls: "bg-green-50 text-green-700" },
    FAILED:   { icon: <XCircle size={12}/>,                      cls: "bg-red-50 text-red-600" },
  }[status];
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${cfg.cls}`}>
      {cfg.icon}{status}
    </span>
  );
}

function ArtifactDot({ ready }: { ready: boolean }) {
  return (
    <span
      title={ready ? "Artifact exists" : "Not yet run"}
      className={`inline-block w-2 h-2 rounded-full ${ready ? "bg-green-500" : "bg-slate-300"}`}
    />
  );
}

function LogPanel({ job, onClose }: { job: Job | null; onClose: () => void }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [job?.logs]);

  if (!job) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-2">
        <Terminal size={28} className="opacity-40"/>
        <p className="text-sm">Run a stage or module to see logs here</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <StatusBadge status={job.status}/>
          <span className="text-xs font-semibold text-slate-700 truncate">{job.name}</span>
          <span className="text-[10px] text-slate-400 shrink-0">#{job.job_id}</span>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-[10px] text-slate-400">{elapsed(job)}</span>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xs">✕</button>
        </div>
      </div>

      {/* log body */}
      <div className="flex-1 overflow-y-auto bg-slate-900 rounded-b-lg font-mono text-[11px] leading-relaxed p-4 whitespace-pre-wrap text-slate-200">
        {job.logs
          ? job.logs
          : job.status === "RUNNING"
            ? <span className="text-slate-500 animate-pulse">Waiting for output…</span>
            : <span className="text-slate-500 italic">No output captured.</span>
        }
        {job.error && (
          <div className="mt-3 p-2 bg-red-900/40 border border-red-700 rounded text-red-300">
            ERROR: {job.error}
          </div>
        )}
        <div ref={bottomRef}/>
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

type Tab = "stages" | "modules";

export function Pipeline() {
  const [tab, setTab]               = useState<Tab>("stages");
  const [stages, setStages]         = useState<StageInfo[]>([]);
  const [pStatus, setPStatus]       = useState<PipelineStatusMap>({});
  const [modules, setModules]       = useState<ModuleInfo[]>([]);
  const [jobs, setJobs]             = useState<Job[]>([]);
  const [activeJob, setActiveJob]   = useState<Job | null>(null);
  const [running, setRunning]       = useState<Record<string, boolean>>({}); // id → busy
  const [refresh, setRefresh]       = useState<Record<string, boolean>>({}); // id → refresh flag
  const [saveModule, setSaveModule] = useState<Record<number, boolean>>({});  // module → save
  const [showHistory, setShowHistory] = useState(true);
  const [toast, setToast]             = useState<{ msg: string; ok: boolean } | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Load stages and modules once ──────────────────────────────────────────
  useEffect(() => {
    fetchStages().then(d => { setStages(d.stages); setPStatus(d.pipeline_status); });
    fetchModules().then(d => setModules(d.modules));
    loadJobs();
  }, []);

  const loadJobs = useCallback(() => {
    fetchJobs().then(d => setJobs(d.jobs));
  }, []);

  // ── Poll active job ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!activeJob || activeJob.status === "SUCCESS" || activeJob.status === "FAILED") {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(async () => {
      const updated = await fetchJob(activeJob.job_id);
      setActiveJob(updated);
      setJobs(prev => prev.map(j => j.job_id === updated.job_id ? updated : j));
      if (updated.status === "SUCCESS" || updated.status === "FAILED") {
        clearInterval(pollRef.current!);
        fetchStages().then(d => setPStatus(d.pipeline_status));
        loadJobs();
        if (updated.status === "SUCCESS") {
          clearApiCache().then(() => {
            setToast({ msg: "Data cache cleared — all dashboard pages will show fresh results.", ok: true });
            setTimeout(() => setToast(null), 5000);
          });
        } else {
          setToast({ msg: `Job failed: ${updated.error ?? "see logs"}`, ok: false });
          setTimeout(() => setToast(null), 7000);
        }
      }
    }, 2000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [activeJob?.job_id, activeJob?.status]);

  // ── Trigger a stage ────────────────────────────────────────────────────────
  const triggerStage = async (stage: string) => {
    setRunning(r => ({ ...r, [stage]: true }));
    try {
      const result = await runStage(stage, !!refresh[stage]);
      const job = await fetchJob(result.job_id);
      setActiveJob(job);
      setJobs(prev => [job, ...prev]);
    } finally {
      setRunning(r => ({ ...r, [stage]: false }));
    }
  };

  // ── Trigger a module ───────────────────────────────────────────────────────
  const triggerModule = async (module: number) => {
    const key = `m${module}`;
    setRunning(r => ({ ...r, [key]: true }));
    try {
      const result = await runModule(module, saveModule[module] !== false);
      const job = await fetchJob(result.job_id);
      setActiveJob(job);
      setJobs(prev => [job, ...prev]);
    } finally {
      setRunning(r => ({ ...r, [key]: false }));
    }
  };

  const handleClearJobs = async () => {
    await clearJobs();
    setJobs([]);
    setActiveJob(null);
  };

  // ── Derive artifact readiness for display ─────────────────────────────────
  const stageKeys = Object.keys(pStatus);

  return (
    <div className="flex flex-col h-full overflow-hidden bg-slate-50">
      {/* ── Toast ───────────────────────────────────────────────────────── */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg text-sm font-medium border ${
          toast.ok
            ? "bg-green-50 border-green-200 text-green-800"
            : "bg-red-50 border-red-200 text-red-800"
        }`}>
          {toast.ok ? <CheckCircle2 size={16} className="text-green-600 shrink-0"/> : <XCircle size={16} className="text-red-500 shrink-0"/>}
          {toast.msg}
          <button onClick={() => setToast(null)} className="ml-2 opacity-50 hover:opacity-100">✕</button>
        </div>
      )}

      {/* ── Page header ─────────────────────────────────────────────────── */}
      <div className="px-6 py-4 border-b border-slate-200 bg-white shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-slate-800">Pipeline Runner</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Execute pipeline stages and intelligence modules — logs stream in real-time
            </p>
          </div>
          <button
            onClick={loadJobs}
            className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700"
          >
            <RefreshCw size={13}/> Refresh
          </button>
        </div>

        {/* tabs */}
        <div className="flex gap-1 mt-3">
          {(["stages", "modules"] as Tab[]).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                tab === t ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-100"
              }`}
            >
              {t === "stages" ? "Pipeline Stages (1–14)" : "Intelligence Modules (1–6)"}
            </button>
          ))}
        </div>
      </div>

      {/* ── Body: two-panel ────────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0 gap-0">

        {/* LEFT — Stage/Module list */}
        <div className="w-[420px] shrink-0 overflow-y-auto border-r border-slate-200 bg-white">
          {tab === "stages" && (
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50 z-10">
                <tr className="text-[10px] uppercase tracking-wide text-slate-400">
                  <th className="pl-4 pr-2 py-2 text-left font-semibold w-12">#</th>
                  <th className="px-2 py-2 text-left font-semibold">Stage</th>
                  <th className="px-2 py-2 text-center font-semibold w-14">Ready</th>
                  <th className="px-2 py-2 text-center font-semibold w-16">Refresh</th>
                  <th className="pr-4 py-2 text-right font-semibold w-16">Run</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {stages.map(({ stage, name }) => {
                  const busy = !!running[stage];
                  // find matching artifact key
                  const ready = stageKeys.some(k => k.includes(`stage${stage.replace(".", "_")}`) && pStatus[k]);
                  return (
                    <tr key={stage} className="hover:bg-blue-50/40 transition-colors">
                      <td className="pl-4 pr-2 py-2.5 font-mono font-bold text-slate-400">{stage}</td>
                      <td className="px-2 py-2.5 text-slate-700 font-medium leading-tight">{name}</td>
                      <td className="px-2 py-2.5 text-center">
                        <ArtifactDot ready={ready}/>
                      </td>
                      <td className="px-2 py-2.5 text-center">
                        <input
                          type="checkbox"
                          checked={!!refresh[stage]}
                          onChange={e => setRefresh(r => ({ ...r, [stage]: e.target.checked }))}
                          className="accent-brand-blue cursor-pointer"
                          title="Force re-run (ignore cache)"
                        />
                      </td>
                      <td className="pr-4 py-2.5 text-right">
                        <button
                          onClick={() => triggerStage(stage)}
                          disabled={busy}
                          className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors ${
                            busy
                              ? "bg-slate-100 text-slate-400 cursor-not-allowed"
                              : "bg-brand-blue text-white hover:bg-blue-700"
                          }`}
                        >
                          {busy
                            ? <Loader2 size={11} className="animate-spin"/>
                            : <Play size={11}/>
                          }
                          {busy ? "Running" : "Run"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          {tab === "modules" && (
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50 z-10">
                <tr className="text-[10px] uppercase tracking-wide text-slate-400">
                  <th className="pl-4 pr-2 py-2 text-left font-semibold w-10">M</th>
                  <th className="px-2 py-2 text-left font-semibold">Module</th>
                  <th className="px-2 py-2 text-center font-semibold w-14">Save</th>
                  <th className="pr-4 py-2 text-right font-semibold w-16">Run</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {modules.map(({ module, name }) => {
                  const key = `m${module}`;
                  const busy = !!running[key];
                  return (
                    <tr key={module} className="hover:bg-blue-50/40 transition-colors">
                      <td className="pl-4 pr-2 py-3 font-mono font-bold text-slate-400">{module}</td>
                      <td className="px-2 py-3 text-slate-700 font-medium leading-snug">{name}</td>
                      <td className="px-2 py-3 text-center">
                        <input
                          type="checkbox"
                          checked={saveModule[module] !== false}
                          onChange={e => setSaveModule(s => ({ ...s, [module]: e.target.checked }))}
                          className="accent-brand-blue cursor-pointer"
                          title="Save outputs to data/processed/"
                        />
                      </td>
                      <td className="pr-4 py-3 text-right">
                        <button
                          onClick={() => triggerModule(module)}
                          disabled={busy}
                          className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors ${
                            busy
                              ? "bg-slate-100 text-slate-400 cursor-not-allowed"
                              : "bg-brand-blue text-white hover:bg-blue-700"
                          }`}
                        >
                          {busy
                            ? <Loader2 size={11} className="animate-spin"/>
                            : <Play size={11}/>
                          }
                          {busy ? "Running" : "Run"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* RIGHT — Log viewer + history */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

          {/* Log panel */}
          <div className="flex-1 min-h-0 p-4 overflow-hidden">
            <div className="h-full bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden flex flex-col">
              <LogPanel job={activeJob} onClose={() => setActiveJob(null)}/>
            </div>
          </div>

          {/* Job history */}
          <div className="shrink-0 border-t border-slate-200 bg-white">
            <button
              onClick={() => setShowHistory(h => !h)}
              className="w-full flex items-center justify-between px-5 py-2.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 transition-colors"
            >
              <span>Job History ({jobs.length})</span>
              <div className="flex items-center gap-2">
                {jobs.length > 0 && (
                  <span
                    onClick={e => { e.stopPropagation(); handleClearJobs(); }}
                    className="flex items-center gap-1 text-red-400 hover:text-red-600 cursor-pointer"
                  >
                    <Trash2 size={11}/> Clear
                  </span>
                )}
                {showHistory ? <ChevronDown size={13}/> : <ChevronUp size={13}/>}
              </div>
            </button>

            {showHistory && (
              <div className="max-h-48 overflow-y-auto">
                {jobs.length === 0 ? (
                  <p className="px-5 py-3 text-xs text-slate-400 italic">No jobs yet. Run a stage or module above.</p>
                ) : (
                  <table className="w-full text-xs">
                    <tbody className="divide-y divide-slate-100">
                      {jobs.map(job => (
                        <tr
                          key={job.job_id}
                          onClick={() => setActiveJob(job)}
                          className={`cursor-pointer hover:bg-blue-50/40 transition-colors ${
                            activeJob?.job_id === job.job_id ? "bg-blue-50" : ""
                          }`}
                        >
                          <td className="pl-5 pr-3 py-2 font-mono text-slate-400 w-20">{job.job_id}</td>
                          <td className="px-2 py-2 w-24"><StatusBadge status={job.status}/></td>
                          <td className="px-2 py-2 text-slate-700 truncate max-w-xs">{job.name}</td>
                          <td className="px-2 py-2 text-slate-400 whitespace-nowrap">{elapsed(job)}</td>
                          <td className="pr-5 py-2 text-slate-400 whitespace-nowrap text-right">{timeAgo(job.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
