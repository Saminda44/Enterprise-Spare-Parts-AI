import { createContext, useContext, useState, type ReactNode } from "react";
import { api } from "./client";

/** The two spare-parts sections. A part's section is its PN_Yamaha brand: OB = OBM, else MC. */
export type Segment = "mc" | "obm";
/** Within MC, the four categories (the CLAUDE.md material-category rule on the part). */
export type Category = "spare_parts" | "lubricant" | "battery" | "tyre";

export const SEGMENT_TEXT: Record<Segment, string> = { mc: "MC", obm: "OBM" };
export const CATEGORY_TEXT: Record<Category, string> = {
  spare_parts: "Spare Parts", lubricant: "Lubricant", battery: "Battery", tyre: "Tyre",
};
const CATEGORY_NOTE: Record<Category, string> = {
  spare_parts: "every MC part except Yamalube, Karate batteries and Katana tyres",
  lubricant: "descriptions containing YAMALUBE (billed sales also count other brands' oils)",
  battery: "descriptions containing KARATE BATTERY",
  tyre: "descriptions containing KATANA TYRE",
};
const CATEGORY_KEY = "mc-category";

// The section and category every API request is scoped to. Set synchronously while a route
// renders, so the page's first requests already carry them; null means no narrowing.
let current: Segment | null = null;
let currentCategory: Category | null = null;

api.interceptors.request.use(config => {
  if (current) config.params = { ...(config.params ?? {}), segment: current };
  if (currentCategory) config.params = { ...(config.params ?? {}), category: currentCategory };
  return config;
});

/** A plain link (Excel downloads) scoped to the current section and category. */
export function withSegment(url: string): string {
  const extra = [current && `segment=${current}`, currentCategory && `category=${currentCategory}`].filter(Boolean);
  if (!extra.length) return url;
  return `${url}${url.includes("?") ? "&" : "?"}${extra.join("&")}`;
}

const SegmentContext = createContext<Segment | null>(null);
const CategoryContext = createContext<Category | null>(null);

/** The section of the page being rendered, or null outside the spare-parts sections. */
export function useSegment(): Segment | null {
  return useContext(SegmentContext);
}

/** The MC category chosen in the category bar, or null for all MC parts. */
export function useCategory(): Category | null {
  return useContext(CategoryContext);
}

function readStoredCategory(): Category | null {
  try {
    const v = localStorage.getItem(CATEGORY_KEY);
    return v && v in CATEGORY_TEXT ? (v as Category) : null;
  } catch {
    return null;
  }
}

/** All MC · Spare Parts · Lubricant · Battery · Tyre — narrows every figure on the page. */
function CategoryBar({ value, onChange }: { value: Category | null; onChange: (c: Category | null) => void }) {
  const options: [Category | null, string][] = [[null, "All MC"], ...(Object.keys(CATEGORY_TEXT) as Category[]).map(k => [k, CATEGORY_TEXT[k]] as [Category, string])];
  return (
    <div className="px-6 pt-4 flex flex-wrap items-center gap-2">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mr-1">MC category</span>
      {options.map(([k, label]) => (
        <button key={k ?? "all"} onClick={() => onChange(k)}
          className={`text-xs px-3 py-1.5 rounded-full border font-medium transition-colors ${
            value === k ? "bg-brand-blue text-white border-brand-blue" : "border-slate-200 text-slate-600 bg-white hover:bg-slate-50"
          }`}>
          {label}
        </button>
      ))}
      {value && <span className="text-[11px] text-slate-400 ml-1">{CATEGORY_NOTE[value]}</span>}
    </div>
  );
}

/**
 * Wrap a route in a spare-parts section. MC pages get the category bar. Pages remount when
 * the section or category changes (the key), so no figure lingers from the previous view.
 */
export function SegmentRoute({ segment, children }: { segment: Segment | null; children: ReactNode }) {
  const [category, setCategory] = useState<Category | null>(readStoredCategory);
  const active = segment === "mc" ? category : null;
  current = segment;
  currentCategory = active;
  const choose = (c: Category | null) => {
    try { if (c) localStorage.setItem(CATEGORY_KEY, c); else localStorage.removeItem(CATEGORY_KEY); } catch { /* storage blocked */ }
    setCategory(c);
  };
  return (
    <SegmentContext.Provider value={segment}>
      <CategoryContext.Provider value={active}>
        {segment === "mc" && <CategoryBar value={active} onChange={choose}/>}
        <div key={`${segment ?? "all"}-${active ?? "all"}`} className="flex-1 flex flex-col overflow-hidden">{children}</div>
      </CategoryContext.Provider>
    </SegmentContext.Provider>
  );
}
