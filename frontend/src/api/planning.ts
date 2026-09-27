// Labels for the policies and safety-stock strategies published by the new pipeline.
export const POLICY_COLORS: Record<string, string> = {
  RS: "#4361EE", RsS: "#7C3AED", ON_DEMAND: "#FFC107", NO_STOCK: "#94A3B8",
};
export const SS_COLORS: Record<string, string> = {
  normal: "#4361EE", empirical: "#7C3AED", bracketing: "#F97316",
};
export function policyLabel(value: string): string {
  return ({ RS: "(R,S)", RsS: "(R,s,S)", ON_DEMAND: "On-demand", NO_STOCK: "No-stock" } as Record<string, string>)[value] ?? value;
}
export function unavailableNumber(value: number | null | undefined): string {
  return value == null ? "Unavailable" : value.toLocaleString();
}
