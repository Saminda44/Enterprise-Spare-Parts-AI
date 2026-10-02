import { useCallback, useEffect, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { AxiosError } from "axios";
import { AlertTriangle, Check, Database, FileSpreadsheet, Loader2, RefreshCw, UploadCloud } from "lucide-react";
import { api } from "../api/client";

type Source = {
  name: string;
  version: string;
  source_modified: string;
  managed: boolean;
  metadata: Record<string, unknown>;
};
type Preview = {
  name: string;
  version: string;
  incoming: number;
  added: number;
  replaced: number;
  unchanged: number;
  conflicts: number;
  result_rows: number;
  warnings: string[];
  notes?: string[];
  summary_updated: boolean;
  applied?: boolean;
  refresh_started?: boolean;
};
const WORKBOOKS = [
  "current_stock.xlsx", "dealers.xlsx", "MCSI.xlsx", "orders.xlsx",
  "sales.xlsx", "On_Orders.xlsx", "PN_Yamaha.xlsx",
];
/** How each workbook is updated, and what its upload must carry (owner, 2026-10-01). */
const RULES: Record<string, { rule: string; columns: string }> = {
  "MCSI.xlsx": {
    rule: "New lines are appended to the end. Lines already in the file are skipped; a changed line is held for review.",
    columns: "Same columns as MCSI.xlsx (key: Billing Document + Item).",
  },
  "orders.xlsx": {
    rule: "New lines are appended to the end. Lines already in the file are skipped; a changed line is held for review.",
    columns: "Same columns as orders.xlsx (key: Sales Document + Item + Schedule Line).",
  },
  "sales.xlsx": {
    rule: "New lines are appended to the end. Lines already in the file are skipped; a changed line is held for review.",
    columns: "Same columns as sales.xlsx (key: Billing Document + Item).",
  },
  "dealers.xlsx": {
    rule: "New dealers are appended. A dealer whose details changed is updated only when the box below is ticked.",
    columns: "Dealer Code, Dealer Name and any other dealer columns.",
  },
  "current_stock.xlsx": {
    rule: "Unrestricted is updated for each Material at its plant and storage location — or, if that number has no row, for the row of the same part under its Latest SS. Rows not in the file keep their quantity; new materials are added.",
    columns: "Material, Plant, Storage Location, Unrestricted (other stock columns optional).",
  },
  "On_Orders.xlsx": {
    rule: "The quantities become the next arrival-month column (after the last month in the file), matched by Material, else by its Latest SS. Materials not in the file yet are added.",
    columns: "Material and one quantity column headed Quantity (Description optional).",
  },
  "PN_Yamaha.xlsx": {
    rule: "New materials are appended. A new supersede number goes into the next empty Supersede column and becomes the Latest SS; older numbers in the same chain follow it. Existing supersedes are never overwritten.",
    columns: "Material plus New Supersede (or Latest SS / numbered Supersede columns); Material description, Type, Group, Brand for new materials.",
  },
};

function errorText(error: unknown): string {
  if (error instanceof AxiosError) {
    const detail = error.response?.data?.detail;
    return typeof detail === "string" ? detail : error.message;
  }
  return error instanceof Error ? error.message : "Upload failed";
}

export function Sources() {
  const [key, setKey] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [backend, setBackend] = useState("excel");
  const [name, setName] = useState("current_stock.xlsx");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [stockDate, setStockDate] = useState("");
  const [replaceDealers, setReplaceDealers] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState<"loading" | "preview" | "apply" | null>(null);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);

  const headers = key ? { "X-Upload-Key": key } : undefined;
  const load = useCallback(async () => {
    setBusy("loading");
    try {
      const response = await api.get<{ backend: string; sources: Source[] }>("/sources", { headers, timeout: 120_000 });
      setSources(response.data.sources);
      setBackend(response.data.backend);
      setMessage(null);
    } catch (error) {
      setMessage({ text: errorText(error), error: true });
    } finally {
      setBusy(null);
    }
  }, [key]);

  useEffect(() => { void load(); }, [load]);

  const selectFile = (next: File | null) => {
    setFile(next);
    setPreview(null);
    setMessage(null);
    if (next) {
      const match = WORKBOOKS.find(item => item.toLowerCase() === next.name.toLowerCase());
      if (match) setName(match);
    }
  };
  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    selectFile(event.dataTransfer.files[0] ?? null);
  };
  const form = () => {
    const data = new FormData();
    data.append("name", name);
    data.append("file", file!);
    data.append("replace_dealers", String(replaceDealers));
    return data;
  };
  const previewUpload = async () => {
    if (!file) return;
    setBusy("preview");
    setMessage(null);
    try {
      const response = await api.post<Preview>("/sources/preview", form(), { headers, timeout: 300_000 });
      setPreview(response.data);
    } catch (error) {
      setPreview(null);
      setMessage({ text: errorText(error), error: true });
    } finally {
      setBusy(null);
    }
  };
  const applyUpload = async () => {
    if (!file || !preview) return;
    setBusy("apply");
    setMessage(null);
    const data = form();
    data.append("expected_version", preview.version);
    if (name === "current_stock.xlsx") data.append("stock_snapshot_as_of", stockDate);
    try {
      const response = await api.post<Preview>("/sources/apply", data, { headers, timeout: 300_000 });
      setPreview(response.data);
      setMessage({
        text: response.data.applied
          ? response.data.refresh_started ? "Source updated. Pipeline refresh started." : "Source updated. Refresh is queued."
          : "No new rows were accepted; source unchanged.",
        error: false,
      });
      await load();
    } catch (error) {
      setMessage({ text: errorText(error), error: true });
    } finally {
      setBusy(null);
    }
  };

  const ready = !!preview && !preview.applied && preview.name === name && !busy
    && (name !== "current_stock.xlsx" || !!stockDate);
  const rule = RULES[name];

  return (
    <div className="h-full overflow-y-auto bg-slate-50 text-slate-800">
      <header className="bg-white border-b border-slate-200 px-6 py-4 flex flex-wrap gap-4 items-center justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <Database size={22} className="text-brand-blue shrink-0" />
          <div><h2 className="text-lg font-bold">Data Sources</h2><span className="text-xs text-slate-500 uppercase font-semibold">{backend} source of record</span></div>
        </div>
        <div className="flex items-center gap-2">
          <input aria-label="Upload API key" title="Upload API key" type="password" value={key} onChange={event => setKey(event.target.value)} placeholder="Upload key" className="w-32 sm:w-44 border border-slate-200 rounded-md px-2 py-1.5 text-xs" />
          <button type="button" title="Refresh source list" onClick={() => void load()} className="p-2 border border-slate-200 rounded-md hover:bg-slate-50"><RefreshCw size={15} /></button>
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-7">
        <section className="grid lg:grid-cols-[minmax(0,1fr)_minmax(290px,380px)] gap-6 items-start">
          <div className="space-y-4 min-w-0">
            <div className="flex flex-wrap gap-3 items-center justify-between"><h3 className="text-sm font-bold uppercase text-slate-600">Upload workbook</h3><Link to="/pipeline" className="text-xs font-semibold text-brand-blue hover:underline">Pipeline status</Link></div>
            <div className="flex flex-wrap gap-3 items-end">
              <label className="text-xs font-semibold text-slate-600 flex-1 min-w-44">Source
                <select value={name} onChange={event => { setName(event.target.value); setPreview(null); }} className="block mt-1 w-full border border-slate-200 rounded-md bg-white px-3 py-2 text-sm text-slate-800">
                  {WORKBOOKS.map(item => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
              {name === "current_stock.xlsx" && <label className="text-xs font-semibold text-slate-600">Stock date
                <input type="date" value={stockDate} onChange={event => setStockDate(event.target.value)} className="block mt-1 border border-slate-200 rounded-md bg-white px-3 py-2 text-sm" />
              </label>}
            </div>
            <label onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop} className={`flex items-center gap-4 cursor-pointer border-2 border-dashed rounded-md px-5 py-8 bg-white transition-colors ${dragging ? "border-brand-blue bg-blue-50" : "border-slate-300 hover:border-brand-blue"}`}>
              <UploadCloud size={27} className="text-brand-blue shrink-0" />
              <span className="min-w-0"><strong className="block text-sm truncate">{file?.name ?? "Drop .xlsx or choose a file"}</strong><span className="text-xs text-slate-500">{file ? `${(file.size / 1048576).toFixed(1)} MB` : "Excel workbooks only"}</span></span>
              <input type="file" accept=".xlsx" className="sr-only" onChange={event => selectFile(event.target.files?.[0] ?? null)} />
            </label>
            {rule && <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 space-y-1">
              <p><span className="font-semibold text-slate-700">How this file is updated: </span>{rule.rule}</p>
              <p><span className="font-semibold text-slate-700">Upload needs: </span>{rule.columns}</p>
            </div>}
            {name === "dealers.xlsx" && <label className="flex gap-2 items-start text-xs text-slate-700"><input type="checkbox" checked={replaceDealers} onChange={event => { setReplaceDealers(event.target.checked); setPreview(null); }} className="mt-0.5 accent-brand-blue" /><span>Replace existing dealer rows when the dealer code matches.</span></label>}
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={!file || !!busy} onClick={() => void previewUpload()} className="inline-flex items-center gap-2 rounded-md bg-brand-blue text-white px-4 py-2 text-sm font-semibold disabled:opacity-50">{busy === "preview" ? <Loader2 size={16} className="animate-spin" /> : <FileSpreadsheet size={16} />}Preview update</button>
              <button type="button" disabled={!ready} onClick={() => void applyUpload()} className="inline-flex items-center gap-2 rounded-md bg-emerald-600 text-white px-4 py-2 text-sm font-semibold disabled:opacity-50">{busy === "apply" ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}Apply update</button>
            </div>
            {message && <div role="status" className={`border-l-4 px-3 py-2 text-sm ${message.error ? "border-red-500 bg-red-50 text-red-800" : "border-emerald-500 bg-emerald-50 text-emerald-800"}`}>{message.text}</div>}
          </div>

          <div className="border border-slate-200 bg-white rounded-md overflow-hidden">
            <h3 className="px-4 py-3 border-b border-slate-200 text-sm font-bold">Update preview</h3>
            {preview ? <>
              <dl className="grid grid-cols-2 text-sm">
                {([ ["Incoming", preview.incoming], ["Added", preview.added], ["Replaced", preview.replaced], ["Unchanged", preview.unchanged], ["Held for review", preview.conflicts], ["Active rows", preview.result_rows] ] as const).map(([label, value]) => <div key={label} className="px-4 py-3 border-b border-slate-100"><dt className="text-xs text-slate-500">{label}</dt><dd className="font-bold tabular-nums">{value.toLocaleString()}</dd></div>)}
              </dl>
              {(preview.notes ?? []).length > 0 && <div className="px-4 py-3 space-y-1.5 border-b border-slate-100">{(preview.notes ?? []).map((note, index) => <p key={index} className="text-xs text-slate-700">{note}</p>)}</div>}
              {preview.summary_updated && <p className="px-4 py-2 text-xs text-slate-600">Sales_Summery.xlsx will also be updated.</p>}
              {preview.warnings.length > 0 && <div className="border-t border-amber-200 bg-amber-50 px-4 py-3 space-y-2">{preview.warnings.map((warning, index) => <p key={index} className="flex gap-2 text-xs text-amber-900"><AlertTriangle size={14} className="shrink-0" />{warning}</p>)}</div>}
            </> : <p className="px-4 py-8 text-center text-xs text-slate-500">No upload preview yet</p>}
          </div>
        </section>

        <section className="min-w-0">
          <h3 className="text-sm font-bold uppercase text-slate-600 mb-3">Active source versions</h3>
          <div className="border border-slate-200 bg-white rounded-md overflow-x-auto max-h-[360px] overflow-y-auto">
            <table className="w-full min-w-[570px] text-sm"><thead className="sticky top-0 bg-slate-100 text-xs text-slate-600"><tr><th className="text-left px-4 py-2">Workbook</th><th className="text-left px-4 py-2">Source</th><th className="text-left px-4 py-2">Updated</th><th className="text-left px-4 py-2">Version</th></tr></thead>
              <tbody className="divide-y divide-slate-100">{sources.map(source => <tr key={source.name}><td className="px-4 py-2 font-medium">{source.name}</td><td className="px-4 py-2 text-slate-500">{source.managed ? "Managed" : "Original"}</td><td className="px-4 py-2 text-slate-500 tabular-nums">{new Date(source.source_modified).toLocaleString()}</td><td className="px-4 py-2 font-mono text-xs text-slate-500">{source.version.slice(0, 12)}</td></tr>)}</tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
