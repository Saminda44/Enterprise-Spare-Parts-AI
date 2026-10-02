interface Props {
  label: string;
  value: string;
  sub?: string;
  color?: "blue" | "green" | "amber" | "red" | "purple" | "teal";
  icon?: React.ReactNode;
}

const COLOR_BORDER: Record<string, string> = {
  blue:   "border-l-brand-blue",
  green:  "border-l-brand-green",
  amber:  "border-l-brand-amber",
  red:    "border-l-brand-red",
  purple: "border-l-brand-purple",
  teal:   "border-l-brand-teal",
};

const COLOR_TEXT: Record<string, string> = {
  blue:   "text-brand-blue",
  green:  "text-brand-green",
  amber:  "text-amber-500",
  red:    "text-brand-red",
  purple: "text-brand-purple",
  teal:   "text-brand-teal",
};

export function KpiCard({ label, value, sub, color = "blue", icon }: Props) {
  return (
    <div className={`min-w-0 bg-white rounded-xl shadow-sm p-5 border-l-4 ${COLOR_BORDER[color]} flex flex-col gap-1`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide break-words">{label}</span>
        {icon && <span className={`text-lg ${COLOR_TEXT[color]}`}>{icon}</span>}
      </div>
      <span className={`text-2xl font-bold ${COLOR_TEXT[color]}`}>{value}</span>
      {sub && <span className="text-xs text-slate-400 break-words">{sub}</span>}
    </div>
  );
}
