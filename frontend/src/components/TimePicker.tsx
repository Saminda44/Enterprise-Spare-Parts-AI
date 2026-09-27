export const TIME_RANGES = ["YTD", "3M", "6M", "1Y", "All"] as const;
export type TimeRange = typeof TIME_RANGES[number];

// ── Year-based helpers ────────────────────────────────────────────────────────

const MONTH_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"] as const;

/** Convert a YYYY-MM period string to a short month label for chart X axes.
 *  singleYear=true → "Jan"; singleYear=false → "Jan '25" */
export function monthLabel(period: string, singleYear = true): string {
  const [yr, m] = period.split("-");
  const abbr = MONTH_ABBR[parseInt(m, 10) - 1] ?? period;
  return singleYear ? abbr : `${abbr} '${yr.slice(2)}`;
}

/** Return unique years present in the data, newest first. */
export function getYears<T extends { period: string }>(data: T[]): number[] {
  return [...new Set(data.map(d => parseInt(d.period.slice(0, 4), 10)))]
    .sort((a, b) => b - a);
}

/** Filter to a single calendar year, or return all data if year is "All". */
export function filterByYear<T extends { period: string }>(
  data: T[],
  year: number | "All",
): T[] {
  if (year === "All") return data;
  return data.filter(d => d.period.startsWith(`${year}-`));
}

/** Dropdown to pick a year (or "All Years"). Newest year listed first. */
export function YearPicker({
  years,
  value,
  onChange,
}: {
  years: number[];
  value: number | "All";
  onChange: (v: number | "All") => void;
}) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value === "All" ? "All" : Number(e.target.value))}
      className="border border-slate-200 rounded-lg px-3 py-1 text-xs font-medium text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-brand-blue/30 cursor-pointer"
    >
      {years.map(y => <option key={y} value={y}>{y}</option>)}
      <option value="All">All Years</option>
    </select>
  );
}

export function TimePicker({
  value,
  onChange,
}: {
  value: TimeRange;
  onChange: (v: TimeRange) => void;
}) {
  return (
    <div className="flex items-center gap-0.5">
      {TIME_RANGES.map(r => (
        <button
          key={r}
          onClick={() => onChange(r)}
          className={`px-2.5 py-1 text-xs rounded font-medium transition-all ${
            value === r
              ? "bg-slate-800 text-white shadow-sm"
              : "text-slate-400 hover:text-slate-700 hover:bg-slate-100"
          }`}
        >
          {r}
        </button>
      ))}
    </div>
  );
}

/** Filter any array with a YYYY-MM `period` field by the selected range. */
export function filterByRange<T extends { period: string }>(
  data: T[],
  range: TimeRange,
): T[] {
  if (range === "All" || data.length === 0) return data;

  if (range === "YTD") {
    const today     = new Date();
    const thisYear  = today.getFullYear();
    const todayStr  = `${thisYear}-${String(today.getMonth() + 1).padStart(2, "0")}`;
    const ytdStart  = `${thisYear}-01`;

    // If the dataset has records between Jan and today, show Jan→today.
    // Otherwise (a past year, or a future forecast-only year) fall back to the most
    // recent year present in the data, in full — never an empty chart.
    const ytd = data.filter(d => d.period >= ytdStart && d.period <= todayStr);
    if (ytd.length > 0) return ytd;
    const maxYear = Math.max(...data.map(d => parseInt(d.period.slice(0, 4), 10)));
    return data.filter(d => d.period.startsWith(`${maxYear}`));
  }

  const months = range === "3M" ? 3 : range === "6M" ? 6 : 12;
  // Anchor to the latest period in the data, not today, so ranges work on
  // historical datasets that don't extend to the current calendar month.
  const maxPeriod = data.reduce((a, b) => (a.period > b.period ? a : b)).period;
  const [maxY, maxM] = maxPeriod.split("-").map(Number);
  const cutoff = new Date(maxY, maxM - months, 1).getTime();
  return data.filter(d => {
    const [y, m] = d.period.split("-").map(Number);
    return new Date(y, m - 1, 1).getTime() >= cutoff;
  });
}
