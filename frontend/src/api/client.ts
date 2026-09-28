import axios from "axios";

export const api = axios.create({ baseURL: "/api/v1", timeout: 30_000 });

// ── Types ──────────────────────────────────────────────────────────────────

export interface PipelineStatus {
  stage1_mcsi: boolean;
  stage2_sales_forecast: boolean;
  stage3_uio_forecast: boolean;
  stage4_orders_eda: boolean;
  stage5_sales_eda: boolean;
  stage6_part_master: boolean;
  stage7_stock_movements: boolean;
  stage8_spare_parts_eda: boolean;
  stage9_classification: boolean;
  stage10_demand_forecast: boolean;
  stage11_stock_tracker: boolean;
  stage12_policy: boolean;
  stage13_shipment_report: boolean;
  stage14_rl_policy: boolean;
}

export interface KpiData {
  total_skus: number;
  active_skus: number;
  stockout_skus: number;
  critical_skus: number;
  excess_skus: number;
  immediate_orders: number;
  soon_orders: number;
  planned_orders: number;
  total_order_value_lkr: number;
  total_stock_value_lkr: number;
  excess_stock_value_lkr: number;
  avg_coverage_months: number;
  sanity_flag_count: number;
  rl_avg_order_reduction_pct: number;
  // Module 6 additions (present when module 6 has run)
  m6_total_skus_to_order?: number;
  m6_critical_count?: number;
  m6_high_count?: number;
  m6_stockout_risk_count?: number;
  m6_overstock_count?: number;
  m6_weighted_fill_rate_pct?: number;
  m6_container_utilization_pct?: number;
  // Module 3 totals
  m3_total_stock_qty?: number;
  m3_total_pipeline_qty?: number;
  m3_total_net_position?: number;
}

export interface PlanningInfo {
  lead_time_months: number;
  review_period_months: number;
  protection_interval_months: number;
  plant: string;
  currency: string;
  cycle_month: string | null;
  policy_verdict: string;
  excess_cover_months: number;
  inventory_position_note: string;
}

export interface PolicyData {
  total: number;
  rows: PolicyRow[];
  urgency_counts: Record<string, number>;
  tier_counts: Record<string, number>;
  ss_method_counts: Record<string, number>;
  total_order_value_lkr: number;
  planning: PlanningInfo;
}

export interface ForecastData {
  total: number;
  rows: ForecastRow[];
  method_counts: Record<string, number>;
  parc_skus: number;
  zero_demand_skus: number;
  all_skus?: number;               // parts forecast, before filters
  monthly_forecast_units?: number; // forecast demand per month, all parts
  fleet_share_pct?: number;        // share of that demand from the fleet term
  planning: PlanningInfo;
}

export interface OverviewData {
  planning: PlanningInfo;
  kpis: KpiData;
  stock_status: Record<string, number>;
  abc_counts: Record<string, number>;
  tier_counts: Record<string, number>;
  urgency_counts: Record<string, number>;
  ss_method_counts: Record<string, number>;
}

export interface ClassificationRow {
  material_9: string;
  active_sku_id: string;
  description: string;
  material_type: string;
  material_group: string;
  brand: string;
  compatible_models: string;
  alias_count: number;
  superseded_numbers: string;
  has_planning: boolean;
  abc: string;
  sales_activity_12m: "ACTIVE" | "INACTIVE";
  order_abc: string;
  planning_abc?: string;                 // the ABC that sets the fill target
  behaviour_source?: string | null;      // what decided the behaviour class
  system?: string | null;                // assembly system (Engine, Electrical, Body, ...)
  catalogue_section?: string | null;     // PDF catalogue section the part sits in
  abc_source?: "sales" | "orders" | null; // sales value, or order value where no sale linked
  sales_xyz?: string | null;
  sales_fsn?: string | null;
  sales_link?: string | null;            // code | description | demand_resolved | demand_split
  sales_qty?: number | null;
  last_sale_month?: string | null;
  sales_net_lkr: number | null;
  billed_lines: number | null;
  xyz: string;
  fsn: string;
  abc_xyz_fsn: string;
  policy_tier: string;
  demand_category: string | null;
  demand_cluster: number | null;
  demand_segment: string | null;
  in_ssop: boolean | null;
  avg_monthly_demand: number | null;
  cv: number | null;
  p_zero: number | null;
  active_months: number | null;
  total_months: number | null;
  total_issue_qty: number | null;
  total_issue_value_lkr: number | null;
  total_return_qty: number | null;
  last_issue_date: string | null;
  part_type: string | null;
}

export interface ForecastRow {
  material_9: string;
  description: string;
  abc: string;
  xyz: string;
  fsn: string;
  policy_tier: string;
  method: string;
  forecast_m1: number;
  forecast_m2: number;
  forecast_m3: number;
  forecast_lt: number;
  avg_monthly_demand: number;
  demand_std_monthly: number;
  demand_std_lt: number;
  cv_hist: number;
  total_issue_value_lkr: number;
  active_months: number;
  demand_category?: string;
  history_forecast?: number;       // own-history forecast per month
  fleet_forecast?: number | null;  // fleet (UIO) forecast per month
  history_weight?: number;         // share of the blend from own history
  protection_demand?: number;      // expected demand over the 4-month protection interval
  protection_p90?: number;         // 90th percentile of that demand
}

export interface MonthlyPoint {
  year_month_str: string;
  issue_qty: number;
  issue_value_lkr: number;
  return_qty: number;
  net_demand: number;
}

export interface InventoryRow {
  material_9: string;
  active_sku_id: string;
  description: string;
  material_type: string;
  material_group: string;
  brand: string;
  compatible_models: string;
  alias_count: number;
  superseded_numbers: string;
  has_planning: boolean;
  has_stock_snapshot: boolean;
  abc: string;
  xyz: string;
  fsn: string;
  policy_tier: string;
  stock_on_hand: number | null;
  stock_value_lkr: number | null;
  coverage_months: number | null;
  days_of_stock: number | null;
  stock_status: string;
  avg_monthly_demand: number | null;
  forecast_lt: number | null;
  method: string;
  total_receipts: number | null;
  total_issues: number | null;
  total_returns: number | null;
  last_movement_date: string | null;
  on_order?: number;                 // units on order (On_Orders.xlsx), in scope
  position_qty?: number;             // on hand + on order
  on_hand_coverage_months?: number | null;
  cover_demand_monthly?: number | null; // demand the cover is measured against
  on_order_value_lkr?: number | null;
  order_qty?: number | null;          // this month's placeable order
}

export interface LocationRow {
  description: string;
  qty: number;
  value_lkr: number | null;
  sku_count: number | null;
  is_excluded: boolean;
}

export interface AtRiskRow {
  material_9: string;
  description: string;
  compatible_models: string;
  abc: string;
  policy_tier: string;
  stock_on_hand: number;
  stock_status: string;
  coverage_months: number;
  net_requirement: number;
  order_urgency: string;
  unit_value_lkr: number;
}

export interface ExcessRow {
  material_9: string;
  description: string;
  compatible_models: string;
  abc: string;
  policy_tier: string;
  stock_on_hand: number;
  stock_value_lkr: number;
  coverage_months: number;
  avg_monthly_demand: number;
}

export interface PolicyRow {
  order_value_lkr: number;
  material_9: string;
  description: string;
  abc: string;
  xyz: string;
  fsn: string;
  policy_tier: string;
  stock_status: string;
  coverage_months: number;
  days_of_stock: number;
  method: string;
  service_level: number;
  z_score: number;
  safety_stock: number;
  ss_method: string;
  rol: number;
  roq: number;
  net_requirement: number;
  order_urgency: string;
  unit_value_lkr: number;
  stock_on_hand: number;
  forecast_lt: number;
  cv: number;
  sanity_flag: boolean;
  sanity_note: string;
}

export interface SanityRow {
  material_9: string;
  description: string;
  abc: string;
  policy_tier: string;
  sanity_note: string;
  rol: number;
  roq: number;
  net_requirement: number;
  avg_monthly_demand: number;
  order_urgency: string;
}

export interface RLRow {
  material_9: string;
  description: string;
  abc: string;
  xyz: string;
  fsn: string;
  policy_tier: string;
  stock_status: string;
  coverage_months: number;
  avg_monthly_demand: number;
  unit_value_lkr: number;
  rl_multiplier: number;
  rl_recommended_qty: number;
  rule_based_roq: number;
  rl_flag: boolean;
}

export interface RLSummary {
  scored_skus: number;
  flagged_skus: number;
  avg_multiplier: number;
  avg_order_reduction_pct: number;
  skus_reduce_order: number;
  skus_increase_order: number;
  skus_unchanged: number;
}

// ── API calls ──────────────────────────────────────────────────────────────

export const fetchPipeline = () =>
  api.get<PipelineStatus>("/overview/pipeline").then(r => r.data);

export const fetchPipelineFreshness = () =>
  api.get<Record<string, string | null>>("/overview/pipeline/freshness").then(r => r.data);

export const fetchOverview = () =>
  api.get<OverviewData>("/overview/kpis").then(r => r.data);

export const fetchClassification = (params?: Record<string, unknown>) =>
  api.get<{
    total: number; rows: ClassificationRow[];
    classified_count: number; unclassified_count: number;
    active_count: number; inactive_count: number;
    order_classified_count: number;
    sales_abc_audit: {
      window_start: string; window_end: string; sales_lines: number;
      code_linked_lines: number; description_linked_lines: number; unmapped_lines: number;
      ambiguous_lines: number; no_match_lines: number;
      linked_skus: number; active_skus: number; return_only_skus: number;
    } | null;
    classification_coverage: Record<string, { assigned: number; not_classified: number }>;
    abc_fsn_counts: Record<string, Record<string, number>>;
    abc_counts: Record<string, number>; xyz_counts: Record<string, number>;
    fsn_counts: Record<string, number>; segment_counts: Record<string, number>;
    demand_category_counts: Record<string, number>; tier_counts: Record<string, number>;
    part_type_counts: Record<string, number>;
  }>("/classification", { params }).then(r => r.data);

export const fetchForecast = (params?: Record<string, unknown>) =>
  api.get<ForecastData>("/forecast", { params }).then(r => r.data);

export const fetchTrend = (sku?: string) =>
  api.get<MonthlyPoint[]>("/forecast/trend", { params: sku ? { sku } : {} }).then(r => r.data);

export const fetchInventory = (params?: Record<string, unknown>) =>
  api.get<{ total: number; rows: InventoryRow[]; classified_count: number; stock_snapshot_count: number; unassessed_count: number; status_counts: Record<string, number>; total_value_lkr: number; excess_value_lkr: number; stockout_regular?: number }>("/inventory", { params }).then(r => r.data);

export const fetchCoverageHistogram = () =>
  api.get<{ bin_start: number; bin_end: number; count: number }[]>("/inventory/coverage-histogram").then(r => r.data);

export const fetchAtRisk = (limit = 50) =>
  api.get<AtRiskRow[]>("/inventory/at-risk", { params: { limit } }).then(r => r.data);

export const fetchExcess = (limit = 100) =>
  api.get<ExcessRow[]>("/inventory/excess", { params: { limit } }).then(r => r.data);

export const fetchStockByLocation = () =>
  api.get<LocationRow[]>("/inventory/stock-by-location").then(r => r.data);

export const fetchPolicy = (params?: Record<string, unknown>) =>
  api.get<PolicyData>("/policy", { params }).then(r => r.data);

export interface ReviewRow {
  material_9: string; description: string; abc: string; fsn: string; policy_tier: string;
  q_review: number; value_review_lkr: number; recent_demand_6m: number; forecast_month: number;
  stock_on_hand: number; on_order: number; review_flags: string;
}
export interface ReviewData { total: number; total_value_lkr: number; no_demand: number; rows: ReviewRow[]; }
/** Lines held for buyer review (order above 3x recent demand) instead of auto-ordered. */
export const fetchOrderReview = (limit = 500) =>
  api.get<ReviewData>("/policy/review", { params: { limit } }).then(r => r.data);

export interface SalesCheckRow {
  part_no: string; description: string; check: string;
  ordered: number; confirmed: number; lost: number; billed: number;
  billed_to_confirmed: number | null; forecast_month: number | null;
  billed_per_month: number; ordered_per_month: number; sales_link: string | null;
}
export interface SalesCheckData {
  total: number; counts: Record<string, number>;
  totals: { ordered?: number; confirmed?: number; billed?: number };
  window: { start: string | null; end: string | null } | null;
  rows: SalesCheckRow[];
}
/** Per part: billed sales vs the orders the forecast is built on, over the overlap window. */
export const fetchSalesCheck = (params?: { check?: string; search?: string; limit?: number }) =>
  api.get<SalesCheckData>("/forecast/sales-check", { params }).then(r => r.data);

export interface OrderPlanRow {
  part_no: string; description: string; status: "to order" | "held for review";
  abc: string; abc_source: string | null; fsn: string; demand_category: string | null;
  behaviour_class: string | null; system: string | null; policy: string; fill_target: number;
  forecast_month: number; history_forecast: number | null; fleet_forecast: number | null;
  history_weight: number; fleet_share: number; protection_demand: number | null;
  safety_stock: number; target_level: number; on_hand: number; on_order: number; position: number;
  gap_to_target: number; eoq: number; q_final: number; q_review: number; unit_cost: number;
  value: number; value_review: number; recent_demand_6m: number; trigger_reason: string; flags: string | null;
}
export interface OrderPlanGroup { name: string; lines: number; value: number; }
export interface OrderPlanData {
  total: number; cycle_month: string; expected_arrival: string;
  summary: {
    lines: number; value: number; units: number; held_lines: number; held_value: number;
    fleet_linked_lines: number; fleet_value_share_pct: number; stock_on_hand: number; stock_on_order: number;
  };
  by_abc: OrderPlanGroup[]; by_system: OrderPlanGroup[]; by_behaviour: OrderPlanGroup[];
  assumptions: {
    fill_targets: Record<string, number>; holding_rate: number; order_cost: number; moq: number;
    pack_size: number; lead_time_months: number; protection_interval_months: number; on_order_interpretation: string;
  };
  rows: OrderPlanRow[];
}
/** The next order: every proposed line with the fleet, class, forecast and stock behind it. */
export const fetchOrderPlan = (params?: Record<string, unknown>) =>
  api.get<OrderPlanData>("/order-plan", { params }).then(r => r.data);

export const fetchSanity = (limit = 200) =>
  api.get<SanityRow[]>("/policy/sanity", { params: { limit } }).then(r => r.data);

export interface UIOAdjustedRow {
  material_9: string;
  description: string;
  abc: string;
  policy_tier: string;
  order_urgency: string;
  primary_model: string;
  uio_current: number;
  uio_historical: number;
  uio_ratio: number;
  base_roq: number;
  uio_adjusted_roq: number;
  delta: number;
  delta_pct: number;
  net_requirement: number;
  stock_on_hand: number;
  unit_value_lkr: number;
}

export interface UIOAdjustedResponse {
  total_skus: number;
  models_covered: number;
  avg_uio_ratio: number;
  rows: UIOAdjustedRow[];
}

export const fetchUIOPlan = (limit = 500) =>
  api.get<UIOAdjustedResponse>("/policy/uio-plan", { params: { limit } }).then(r => r.data);

export interface UIOServicePlanRow {
  material_9: string;
  description: string;
  abc: string;
  policy_tier: string;
  order_urgency: string;
  catalog_models: string;
  hist_months: number;
  hist_demand_total: number;
  avg_monthly: number;
  service_plan_qty: number;
  base_roq: number;
  net_requirement: number;
  recommended_order: number;
  delta_vs_roq: number;
  delta_pct: number;
  stock_on_hand: number;
  unit_value_lkr: number;
  in_catalog: boolean;
}

export interface UIOServicePlanResponse {
  planning: PlanningInfo;
  total_skus: number;
  skus_with_history: number;
  horizon_months: number;
  avg_monthly_demand_total: number;
  total_service_plan_value: number;
  total_rule_based_value: number;
  value_delta: number;
  rows: UIOServicePlanRow[];
}

export const fetchUIOServicePlan = (horizon_months?: number, limit = 500) =>
  api.get<UIOServicePlanResponse>("/policy/uio-service-plan", { params: { horizon_months, limit } }).then(r => r.data);

export const fetchRL = (params?: Record<string, unknown>) =>
  api.get<{ summary: RLSummary; rows: RLRow[] }>("/rl", { params }).then(r => r.data);

// ── Stage 1-3: Bikes ───────────────────────────────────────────────────────

export interface McsiModelRow   { model: string; count: number; pct: number; }
export interface McsiProvinceRow { province: string; count: number; }
export interface McsiMonthlyPoint { period: string; sold: number; revenue_lkr: number; }
export interface McsiSummary {
  total_sold: number;
  date_from: string; date_to: string;
  by_model: McsiModelRow[];
  by_province: McsiProvinceRow[];
  monthly_trend: McsiMonthlyPoint[];
}
export interface SalesForecastRow {
  period: string; forecast: number; lower_80: number; upper_80: number;
  actual: number | null; is_forecast: boolean;
  target: number | null; target_gap: number | null;
}
export interface UIOForecastRow {
  period: string; new_sales: number; uio_total: number; attrition: number;
  is_forecast: boolean; lower_80: number | null; upper_80: number | null;
}
export interface BikesData {
  mcsi: McsiSummary;
  sales_forecast: SalesForecastRow[];
  uio_forecast: UIOForecastRow[];
  forecast_method?: string;   // the published method's label
}

export const fetchBikes = () =>
  api.get<BikesData>("/bikes").then(r => r.data);

export interface SalesTargets {
  yearly_target: number;
  monthly_overrides: Record<string, number>;
}
export const fetchTargets = () =>
  api.get<SalesTargets>("/bikes/targets").then(r => r.data);
export const saveTargets = (body: SalesTargets) =>
  api.post<{ ok: boolean }>("/bikes/targets", body).then(r => r.data);

// ── Stage 1: MCSI EDA ─────────────────────────────────────────────────────

export interface McsiEdaKpis {
  total_vins: number; sold: number; returned: number; return_rate_pct: number;
  total_revenue_lkr: number; avg_monthly_units: number; avg_revenue_per_unit: number;
  active_provinces: number; active_dealers: number; models_sold: number;
  date_from: string; date_to: string; months_of_data: number;
  /** SlsVolQty -1 rows, and the VINs re-invoiced after one: not returns. */
  billing_reversals?: number; rebilled_vins?: number;
}
export interface McsiEdaYearRow  { year: number; units_sold: number; revenue_lkr: number; avg_monthly: number; }
export interface McsiEdaModelRow {
  model: string;
  /** MCSI model name ("FZ FI V2") and the "Name (Code)" label built from it. */
  model_description?: string; model_label?: string;
  units_sold: number; revenue_lkr: number; share_pct: number; avg_revenue_per_unit: number;
}
export interface McsiEdaProvinceRow { province: string; units_sold: number; revenue_lkr: number; share_pct: number; dealer_count: number; }
export interface McsiColorRow    { model: string; color: string; units_sold: number; }
export interface McsiRmRow       { rm: string; units_sold: number; revenue_lkr: number; dealer_count: number; ase_count: number; share_pct: number; avg_revenue_per_unit: number; }
export interface McsiAseRow      { ase: string; rm: string; units_sold: number; revenue_lkr: number; dealer_count: number; share_pct: number; }
export interface McsiDistrictRow { province: string; district: string; units_sold: number; revenue_lkr: number; share_pct: number; }
export interface McsiEdaData {
  kpis: McsiEdaKpis;
  monthly_trend: McsiMonthlyPoint[];
  by_year: McsiEdaYearRow[];
  by_model: McsiEdaModelRow[];
  by_province: McsiEdaProvinceRow[];
  by_color: McsiColorRow[];
  by_rm: McsiRmRow[];
  by_ase: McsiAseRow[];
  by_district: McsiDistrictRow[];
}
export interface ModelPriceRow {
  model: string; label: string; motorcycle_type: string | null; segment: string | null; cc: number | null;
  list_price: number; avg_price: number; min_price: number; units: number; unit_share_pct: number;
  revenue_lkr: number; revenue_share_pct: number; discounted_units: number; discounted_pct: number;
  avg_discount: number; units_per_month: number; months_sold: number; price_band: string;
}
export interface ModelPriceData {
  totals: { units: number; revenue_lkr: number; discounted_units: number; avg_price: number; date_from: string; date_to: string };
  models: ModelPriceRow[];
  monthly: { model: string; period: string; units: number; avg_price: number; discounted_units: number }[];
  bands: { band: string; models: number; units: number; unit_share_pct: number; revenue_lkr: number }[];
}
/** Model list price against bikes sold, discounts and price bands (MCSI). */
export const fetchModelPrice = () => api.get<ModelPriceData>("/bikes/model-price").then(r => r.data);

export interface BuyerAgeData {
  bands: { band: string; units: number; share_pct: number | null }[];
  totals: { units: number; units_with_age: number; median_age: number | null; under_26_pct: number };
  models: { model: string; label: string; units: number; units_with_age: number | null; median_age: number | null; mean_age: number | null; under_26_pct: number | null }[];
  cube: { band: string; model: string; colour: string; units: number }[];
}
/** Bikes sold by buyer age band, model and colour (MCSI; counts only). */
export const fetchBuyerAge = () => api.get<BuyerAgeData>("/bikes/buyer-age").then(r => r.data);

export const fetchMcsiEda = () => api.get<McsiEdaData>("/bikes/mcsi-eda").then(r => r.data);

export interface ModelForecastRow {
  period: string; model: string;
  actual: number | null; forecast: number; is_forecast: boolean;
}
export interface ModelForecastInfo {
  model: string;            // "Name (Code)"
  code: string;
  is_active: boolean;       // Active in Sales Summery's Model Classification
  history_months: number;   // months with a registration
}
export interface ModelForecastData {
  models: string[];
  active_models?: string[];
  model_info?: ModelForecastInfo[];
  rows: ModelForecastRow[];
}
export interface BacktestStats {
  forecast: number; actual: number;
  error_pct: number | null;   // (forecast − actual) ÷ actual over scored months
  wape_pct: number | null;    // Σ|forecast − actual| ÷ Σ actual, month by month
}
export interface ForecastBacktest {
  train_start: string; train_end: string; horizon: number;
  scored_periods: string[];
  methods: { key: string; label: string }[];
  recommended?: string;
  published?: string;         // key of the method the forward forecast is published with
  summary: ({ key: string } & BacktestStats)[];
  history: { period: string; train_actual: number }[];
  monthly: ({ period: string; actual: number | null; actual_new_models: number | null } & Record<string, number | string | null>)[];
  models: ({ model: string; train_months: number } & Record<string, BacktestStats | string | number>)[];
  new_models: { model: string; actual: number }[];
  /** One row per model and forecast month; method keys hold that method's forecast. */
  model_monthly?: ({ model: string; period: string; is_new: boolean; actual: number | null } & Record<string, number | string | boolean | null>)[];
}
export const fetchForecastBacktest = (train_start: string, train_end: string, horizon = 12) =>
  api.get<ForecastBacktest>("/bikes/forecast/backtest", { params: { train_start, train_end, horizon } })
    .then(r => r.data);

export const fetchModelForecast = () =>
  api.get<ModelForecastData>("/bikes/forecast/by-model").then(r => r.data);

export interface UIOExternalRow { model: string; total_sales_units: number; uio: number; }
export interface UIOSummaryRow  { model: string; uio: number; uio_pct: number; }
export interface UIOComparisonData {
  external: UIOExternalRow[];  // UIO.xlsx — full historical fleet (all model generations)
  mcsi: UIOSummaryRow[];       // MCSI.xlsx — recent VIN-verified bikes
}
export interface UioGroupRow { name: string; registered: number; uio: number; uio_low: number; uio_high: number; share_pct: number; }
export interface UioSnapshot {
  as_of_year: number | null;
  first_year?: number;
  kpis: {
    registered: number; uio: number; uio_low: number; uio_high: number; surviving_pct: number;
    active_uio_pct: number; avg_age: number; models_total: number; models_active: number; models_in_parc: number;
  };
  series: { year: number; new_sales: number; uio: number; uio_low: number; uio_high: number; attrition: number }[];
  registrations: { year: number; type: string; units: number }[];
  by_family: UioGroupRow[]; by_segment: UioGroupRow[]; by_type: UioGroupRow[]; by_status: UioGroupRow[];
  age: { bucket: string; age_start: number; type: string; units: number }[];
  colour: { name: string; units: number }[];
  models: {
    model: string; family: string; type: string; segment: string; cc: number | null; status: string;
    first_year: number | null; last_year: number | null; registered: number;
    uio: number; uio_low: number; uio_high: number; surviving_pct: number | null; avg_age: number | null;
  }[];
}
/** The fleet from Sales Summery: registrations and the estimated units in operation. */
export const fetchUioSnapshot = () => api.get<UioSnapshot>("/bikes/uio-snapshot").then(r => r.data);

export const fetchUIOComparison = () =>
  api.get<UIOComparisonData>("/bikes/uio").then(r => r.data);

export interface UIODemandRow {
  material_9: string; description: string; compatible_models: string | null;
  model_count: number; avg_monthly: number; hist_months: number;
  model_uio_total: number; replacement_freq_per_uio: number;
  projected_uio: number; uio_demand_monthly: number;
  uio_demand_leadtime: number; supply_pct_applied: number;
}
export interface UIODemandData {
  total_parts: number; parts_with_demand: number; projected_uio: number;
  supply_pct: number; lead_time_months: number;
  sum_uio_demand_monthly: number; sum_uio_demand_leadtime: number;
  rows: UIODemandRow[];
}
export const fetchUIODemand = (minDemand = 0) =>
  api.get<UIODemandData>("/bikes/uio-demand", { params: { min_demand: minDemand } }).then(r => r.data);

export interface DealerRow {
  province: string; rm: string; ase: string;
  dealer: string; dealer_code: string;
  units_sold: number; revenue_lkr: number;
}
export interface DealersData {
  total_dealers: number; total_units: number; total_revenue_lkr: number;
  available_years: number[];
  rows: DealerRow[];
}
export const fetchBikeDealers = (limit = 500, year?: number) =>
  api.get<DealersData>("/bikes/dealers", { params: { limit, ...(year ? { year } : {}) } }).then(r => r.data);

export interface CrosstabRow { province: string; totals: Record<string, number>; }
export interface CrosstabData { models: string[]; rows: CrosstabRow[]; }
export const fetchCrosstab = (year?: number) =>
  api.get<CrosstabData>("/bikes/crosstab", { params: year ? { year } : {} }).then(r => r.data);

export interface DealerModelRow { dealer: string; dealer_code: string; province: string; rm: string; ase: string; total: number; totals: Record<string, number>; }
export interface DealerModelMatrix { models: string[]; rows: DealerModelRow[]; }
export const fetchDealerModelMatrix = () =>
  api.get<DealerModelMatrix>("/bikes/dealer-model-matrix").then(r => r.data);

export interface GeoMatrixRow { entity: string; total: number; totals: Record<string, number>; }
export interface GeoMatrixLevel { models: string[]; rows: GeoMatrixRow[]; }
export interface GeoModelData { rm: GeoMatrixLevel; ase: GeoMatrixLevel; province: GeoMatrixLevel; district: GeoMatrixLevel; }
export const fetchGeoModel = () =>
  api.get<GeoModelData>("/bikes/geo-model").then(r => r.data);

export type GeoColorData = GeoModelData; // same shape, "models" field holds color names
export const fetchGeoColor = () =>
  api.get<GeoColorData>("/bikes/geo-color").then(r => r.data);

// same shape — "models" field holds "ModelName – Color" combo strings
export const fetchGeoModelColor = () =>
  api.get<GeoModelData>("/bikes/geo-model-color").then(r => r.data);

export interface TargetBreakdownRow {
  model: string; color: string;
  historical_units: number; share_pct: number;
  allocated_units: number;          // whole units; colours sum to the model, models to the target
  window_start?: string; window_end?: string;   // the sales-mix window
}
export const fetchTargetBreakdown = (monthKey: string, target: number) =>
  api.get<TargetBreakdownRow[]>("/bikes/target-breakdown", { params: { month_key: monthKey, target } }).then(r => r.data);

export interface MonthlyAllocationRow extends TargetBreakdownRow { period: string; }
/** Each month's target split to models and colours, whole units; each month sums to its target. */
export const fetchMonthlyAllocation = (targets: Record<string, number>) =>
  api.post<MonthlyAllocationRow[]>("/bikes/target-breakdown/monthly", { targets }).then(r => r.data);

export interface ActualModelColourRow { period: string; model: string; color: string; units: number; is_active?: boolean; }
/** Sold units per active model, colour and month for one year. */
export const fetchActualModelColour = (year: number) =>
  api.get<ActualModelColourRow[]>("/bikes/actual-model-colour", { params: { year } }).then(r => r.data);

export interface UpliftFactorsRow {
  month_key: string;
  promotion_pct: number;
  new_model_pct: number;
  dealer_pct: number;
  pricing_pct: number;
  other_pct: number;
}
export const fetchUpliftInputs = () =>
  api.get<UpliftFactorsRow[]>("/bikes/uplift-inputs").then(r => r.data);
export const saveUpliftInputs = (rows: UpliftFactorsRow[]) =>
  api.post<{ ok: boolean }>("/bikes/uplift-inputs", rows).then(r => r.data);
export const fetchDealerUpliftBaseline = () =>
  api.get<Record<string, number>>("/bikes/dealer-uplift-baseline").then(r => r.data);

// ── Stage 6: Part Master ───────────────────────────────────────────────────

export interface PartMasterRow {
  part_number: string; description: string;
  compatible_models: string | null;
  order_qty: number; eod_rate: number; stock: number; on_order: number;
  revised_order_qty: number; forecast_monthly_qty: number;
  superseded_from: string | null; has_supersession: boolean;
  part_type: string | null;
}
export interface SupersessionRow {
  requested_pn: string; current_pn: string; hops: number;
  current_description: string; old_description: string;
}
export interface PartMasterData {
  total: number; supersession_count: number;
  rows: PartMasterRow[]; supersessions: SupersessionRow[];
}

export const fetchParts = (params?: Record<string, unknown>) =>
  api.get<PartMasterData>("/parts", { params }).then(r => r.data);

export interface CatalogDerivedPartRow {
  part_no: string;
  description: string;
  section: string;
  compatible_models: string;
  variant_count: number | null;
  source_count: number | null;
  kind: string;
  /** PN_Yamaha database rows only. */
  latest_ss?: string;
  /** The catalogue's part name, when the material is found in a catalogue. */
  catalogue_description?: string;
  /** Which PN_Yamaha number matched: material, latest_ss, supersede_1 ... supersede_10. */
  matched_on?: string;
  catalogue_part_nos?: string;
  in_catalogue?: boolean;
  /** PN_Yamaha 1st..10th Supersede, in order; "" where the chain is shorter. */
  supersedes?: string[];
}
export interface PartCompatibilitySummary {
  /** "catalogue_database", or "step_02" when the database could not be reached. */
  source: "catalogue_database" | "step_02";
  error?: string;
  catalogue_part_numbers?: number;
  /** Catalogue part numbers with no PN_Yamaha identity (not shown on this page). */
  catalogue_part_numbers_not_in_master?: number;
  parts_with_models?: number;
  brand?: string;
  materials?: number;
}
export interface CatalogDerivedPartsData {
  indexed: boolean;
  /** "pn_yamaha_db" = PN_Yamaha Brand YM from the database; "PN_Yamaha" = Step 02. */
  source?: string;
  compatibility?: PartCompatibilitySummary;
  /** True when data comes from the agent-derived part master (richer). */
  agent_master?: boolean;
  total: number;
  total_models: number;
  rows: CatalogDerivedPartRow[];
  models: string[];
}
export const fetchPartsFromCatalog = (params?: Record<string, unknown>) =>
  api.get<CatalogDerivedPartsData>("/parts/master-view", { params, timeout: 60_000 }).then(r => r.data);

export interface PartMasterRebuildStatus {
  running: boolean;
  last_result: {
    ok: boolean;
    total_parts?: number;
    total_pdfs?: number;
    agents_run?: number;
    agents_skipped?: number;
    agent_errors?: string[];
    error?: string;
  } | null;
  parquet_exists: boolean;
  parquet_size_kb: number;
  cached_pdfs: number;
}
export const fetchPartMasterStatus = () =>
  api.get<PartMasterRebuildStatus>("/catalog/part-master/status").then(r => r.data);
export const rebuildPartMaster = (runMissingAgents = true) =>
  api.post<{ queued: boolean; message: string }>(
    `/catalog/part-master/rebuild?run_missing_agents=${runMissingAgents}`
  ).then(r => r.data);

// ── Stages 4,5,7,8: EDA ────────────────────────────────────────────────────

export interface OrdersEdaDealer { dealer: string; order_count: number; total_value_lkr: number; }
export interface OrdersEdaMonthlyPoint { period: string; po_count: number; return_count: number; total_value_lkr: number; confirmed_value_lkr: number; }
export interface OrdersEdaRejectionRow {
  material: string; description: string; customer: string; document_date: string;
  order_qty: number; lost_qty: number; fill_rate: number;
}
export interface OrdersEdaRejectionReasonRow {
  reason: string; rejected_lines: number; rejected_qty: number; share_pct: number;
}
export interface CategoryMixRow {
  segment: string; order_lines: number; value_lkr: number;
  value_share_pct: number; fill_rate_pct: number;
}
export interface YoYGrowthRow {
  segment: string;
  year_prev: number;
  year_curr: number;
  value_year_prev: number;
  value_year_curr: number;
  yoy_pct: number;
  lines_year_prev: number;
  lines_year_curr: number;
  period?: string;   // months compared in both years, e.g. "Jan–Aug"
}
export interface ProvincePerformanceRow {
  province: string; order_value_lkr: number;
  value_share_pct: number; fill_rate_pct: number; dealer_count: number;
}
export interface ShortShipRow {
  material: string; description: string;
  short_qty: number; fill_rate_pct: number; occurrences: number;
}
export interface FillRateBandRow {
  segment: string; above_98: number; between_95_98: number;
  between_90_95: number; below_90: number;
}
export interface PartAnalysisRow {
  material: string; description: string;
  order_lines: number; order_qty: number; confirmed_qty: number;
  total_value_lkr: number; fill_rate_pct: number; value_share_pct: number; short_qty: number;
}
export interface DealerPerfRow {
  dealer_code: string; dealer_name: string; province: string; district: string; rm: string; ase: string;
  po_lines: number; order_value_lkr: number; fill_rate_pct: number;
  return_rate_pct: number; dealer_tier: string; value_share_pct: number;
}
export interface RmPerfRow {
  rm: string;
  province: string;
  unique_dealers: number;
  po_lines: number;
  order_value_lkr: number;
  fill_rate_pct: number;
  return_rate_pct: number;
  value_share_pct: number;
}
export interface AsePerfRow {
  ase: string; rm: string; province: string; unique_dealers: number; po_lines: number;
  order_value_lkr: number; fill_rate_pct: number; return_rate_pct: number;
}
export interface DistrictPerfRow {
  province: string;
  district: string;
  unique_dealers: number;
  po_lines: number;
  order_value_lkr: number;
  fill_rate_pct: number;
  value_share_pct: number;
  return_rate_pct: number;
}
export interface ProvinceAnalysisRow {
  province: string; unique_dealers: number; po_lines: number;
  order_value_lkr: number; fill_rate_pct: number; return_rate_pct: number; value_share_pct: number;
}

export interface McMonthlyCategoryPoint {
  period: string;
  lubricant_lkr: number;
  battery_lkr: number;
  tyre_lkr: number;
  spare_parts_lkr: number;
  total_lkr: number;
}

export interface FulfillmentLineBucket {
  lines: number;
  pct_of_lines: number;
  order_qty: number;
  confirmed_qty: number;
  confirmed_value_lkr: number;
}

export interface FulfillmentAnalysis {
  total_lines: number;
  fully_confirmed: FulfillmentLineBucket;
  partially_confirmed: FulfillmentLineBucket;
  fully_rejected: FulfillmentLineBucket;
  total_docs: number;
  docs_fully_filled: number;
  docs_fully_filled_pct: number;
  docs_partially_filled: number;
  docs_partially_filled_pct: number;
  docs_complete_zero: number;
  docs_complete_zero_pct: number;
}

export interface OrdersEdaData {
  data_year: number;          // the year KPIs are computed for (0 = unknown)
  available_years: number[];  // years available for the year picker
  total_po: number; total_returns: number; avg_fill_rate: number;
  period_label?: string;            // e.g. "2026 Jan–Aug" for a part year
  lost_quantity?: number;
  prior_period?: { year: number; label: string; order_lines: number; ordered_value: number; ordered_quantity: number; lost_quantity: number; fill_rate: number } | null;
  avg_lead_time_days: number; fill_rate_lt1_count: number;
  total_order_value_lkr: number;    // Order Received value (all PO lines incl. rejected)
  total_confirmed_value_lkr: number; // Total Sales value (confirmed qty × unit price)
  value_fill_rate_pct: number;       // total_confirmed / total_order × 100
  total_return_value_lkr: number;   // Net value of H-type Return Order lines only
  return_rate_value_pct: number;    // return_value / order_value × 100
  unfulfill_value_lkr: number;      // ordered value not confirmed (PO ordered − PO confirmed)
  sales_qty: number;                // total confirmed quantity on PO lines
  unique_skus: number;              // unique materials on PO lines
  total_po_documents: number;       // unique purchase order document count
  return_order_reasons: OrdersEdaRejectionReasonRow[];
  return_type_breakdown: Record<string, number>;
  top_dealers: OrdersEdaDealer[];
  monthly_trend: OrdersEdaMonthlyPoint[];
  rejections: OrdersEdaRejectionRow[];
  orders_received_breakdown: { total_documents: number; fully_filled: number; partial_fill: number; complete_zero: number; };
  rejection_reasons: OrdersEdaRejectionReasonRow[];
  // Per-segment analysis tables
  part_analysis: PartAnalysisRow[];
  dealer_perf: DealerPerfRow[];
  rm_perf: RmPerfRow[];
  ase_perf: AsePerfRow[];
  district_perf: DistrictPerfRow[];
  province_analysis: ProvinceAnalysisRow[];
  // Business insights (full dataset)
  category_mix: CategoryMixRow[];
  yoy_growth: YoYGrowthRow[];
  province_perf: ProvincePerformanceRow[];
  top_short_shipped: ShortShipRow[];
  fill_rate_bands: FillRateBandRow[];
  dealer_health_summary: { a_tier: number; b_tier: number; c_tier: number; dormant_count: number; total_dealers: number; };
  pareto_summary: { sku_80pct_count: number; total_skus: number; dealer_80pct_count: number; total_dealers: number; };
  category_cross: { multi_category: number; single_category: number; total_mc_dealers: number; };
  rejection_rate_pct: number;
  fraud_alerts: Array<{ dealer_code: string; dealer_name: string; month: string; return_share_pct: number; }>;
  mc_monthly_category: McMonthlyCategoryPoint[];
  fulfillment?: FulfillmentAnalysis;
}

export interface SalesEdaMonthlyPoint {
  period: string;
  sale_value_lkr: number;
  return_value_lkr: number;
  net_value_lkr: number;
  sale_qty: number;
  return_qty: number;
  order_received_lkr: number;
}

export interface SalesPartRow {
  material: string;
  sale_lines: number;
  sale_qty: number;
  sale_value_lkr: number;
  return_lines: number;
  return_qty: number;
  return_value_lkr: number;
  net_qty: number;
  net_value_lkr: number;
  return_rate_pct: number;
}

export interface SalesDealerRow {
  dealer_name: string;
  dealer_type: string;
  province: string;
  district: string;
  ase: string;
  rm: string;
  sale_qty: number;
  sale_value_lkr: number;
  return_qty: number;
  return_value_lkr: number;
  return_rate_pct: number;
  unique_skus: number;
  order_received_lkr: number;
  fulfillment_pct: number;
}

export interface SalesHierRow {
  rm?: string; ase?: string; district?: string; province?: string;
  sale_value_lkr: number;
  return_value_lkr: number;
  return_rate_pct: number;
  sale_qty: number;
  dealer_count: number;
  unique_skus: number;
  order_received_lkr?: number;
}

export interface SalesMcCategoryRow {
  mc_category: string;
  sale_lines: number;
  sale_qty: number;
  sale_value_lkr: number;
  return_value_lkr: number;
  value_share_pct: number;
  return_rate_pct: number;
  unique_skus: number;
}

export interface SalesMcMonthlyPoint {
  period: string;
  lubricant_lkr: number;
  battery_lkr: number;
  tyre_lkr: number;
  spare_parts_lkr: number;
  total_lkr: number;
}

export interface SalesEdaData {
  data_year: number;
  available_years: number[];
  total_sale_value_lkr: number;
  total_return_value_lkr: number;
  net_sale_value_lkr: number;
  return_rate_pct: number;
  total_sale_qty: number;
  total_return_qty: number;
  unique_parts: number;
  unique_dealers: number;
  total_sale_lines: number;
  total_return_lines: number;
  order_received_lkr: number;
  fulfillment_pct: number;
  monthly_trend: SalesEdaMonthlyPoint[];
  part_analysis: SalesPartRow[];
  dealer_perf: SalesDealerRow[];
  rm_perf: SalesHierRow[];
  ase_perf: SalesHierRow[];
  district_perf: SalesHierRow[];
  province_perf: SalesHierRow[];
  mc_category_mix: SalesMcCategoryRow[];
  mc_monthly_category: SalesMcMonthlyPoint[];
}

export interface MovementMonthlyPoint { period: string; movement_class: string; qty: number; value_lkr: number; }
export interface MovementsData {
  total_records: number; date_from: string; date_to: string;
  by_class: Record<string, number>; monthly_trend: MovementMonthlyPoint[];
}

export interface PZeroBin { bin: string; lo: number; hi: number; count: number; }
export interface IngestionLogRow { filename: string; rows_in: number; inserted: number; duplicates_skipped: number; }
export interface TopSkuRow {
  rank: number; material_9: string; description: string;
  demand_category: string | null;
  total_issue_value_lkr: number; total_issue_qty: number; cumulative_share_pct: number;
}
export interface IntermittentSkuRow {
  material_9: string; description: string; demand_category: string;
  p_zero: number; cv: number; active_months: number;
  avg_monthly_demand: number; total_issue_value_lkr: number;
}
export interface SparePartsEdaData {
  total_skus: number; in_ssop_count: number;
  total_issue_value_lkr: number; median_cv: number; median_p_zero: number;
  demand_category_counts: Record<string, number>;
  p_zero_bins: PZeroBin[];
  ingestion_summary: IngestionLogRow[];
  top_skus: TopSkuRow[];
  intermittent_skus: IntermittentSkuRow[];
}

export interface CatalogFile  { filename: string; rel_path: string; size_kb: number; }
export interface CatalogModel { model: string; pdf_count: number; files: CatalogFile[]; }
export interface CatalogData  { models: CatalogModel[]; total_pdfs: number; }
export const fetchCatalog = () => api.get<CatalogData>("/catalog").then(r => r.data);
export const catalogFileUrl = (rel_path: string) =>
  `/api/v1/catalog/file/${rel_path.split("/").map(encodeURIComponent).join("/")}`;
export interface ColourCode {
  abbreviation: string;  // e.g. "CM6"
  name: string;          // e.g. "CYAN METALLIC 6"
  code: string;          // e.g. "1344"
  // A model colour for this PDF. Set from a (*) in the applicable-colour table's
  // abbreviation column where the PDF carries one; otherwise resolved from the
  // document — see model_colour_source on PdfTableResult.
  is_model_colour: boolean;
}

export interface PdfTableResult {
  headers: string[]; rows: string[][]; total: number; sections: string[];
  /** "database" = the stored copy; "pdf" = read live (not loaded, changed, or DB unreachable). */
  source?: "database" | "pdf";
  variants: string[];
  colour_codes: ColourCode[];
  available_colours?: string[];
  /** How is_model_colour was decided: "marked" (a (*) row), "parts", "listed", "none". */
  model_colour_source?: "marked" | "single" | "parts" | "listed" | "none";
  manufacture_year?: string;
  model_no?: string;
  pages_scanned: number; sections_found: number; ocr_flagged: number; warnings: string[];
  column_layout?: string[];  // detected column names in left-to-right order
  column_display_labels?: Record<string, string>; // logical key → PDF's actual header text
  desc_colour_mode?: boolean;  // true when colours come from description parentheses
  desc_colour_hints?: Record<string, string>; // part_no → colour_abbr for desc-colour PDFs
}
export const fetchPdfTables = (rel_path: string) =>
  api.get<PdfTableResult>(
    `/catalog/tables/${rel_path.split("/").map(encodeURIComponent).join("/")}`,
    { timeout: 120_000 },
  ).then(r => r.data);

// ── Catalogue Agent ────────────────────────────────────────────────────────

export interface AgentPartRow {
  figure: string;
  ref_no: string;
  part_no: string;
  description: string;
  qty: string;
  remarks: string;
  kind: "shared" | "colour_specific";
}

export interface AgentBuild {
  variant: string;
  colour: string;
  colour_name: string;
  colour_code: string;
  part_count: number;
  parts: AgentPartRow[];
}

export interface AgentColourEntry {
  name: string;
  code: string;
  is_model_colour: boolean;
  web_confirmed?: boolean;
  has_external_parts?: boolean;
}

/** One colour option in a variant's colour list (from the foreword colour table). */
export interface VariantColourEntry {
  abbreviation: string;   // e.g. "CM6"
  name: string;           // e.g. "CYAN METALLIC 6"
  code: string;           // paint code, e.g. "1344"
  is_model_colour: boolean;
}

export interface ColourChangingPart {
  section: string;
  ref_no: string;
  description: string;
  /** colour abbreviation → part number */
  per_colour: Record<string, string>;
}

export interface AgentResult {
  source_pdf: string;
  extracted_at: string;
  model: string;
  model_no?: string;
  manufacture_year?: string;
  variants: string[];
  colour_legend: Record<string, AgentColourEntry>;
  rosters: Record<string, string[]>;
  builds: AgentBuild[];
  validated_colours?: string[];
  web_colour_names?: string[];
  warnings: string[];
  /** Server-computed mapping: available_colour_caption → colour_abbreviation */
  available_colour_map?: Record<string, string>;
  /** Per-variant ordered colour list in foreword-table order. */
  variant_colour_map?: Record<string, VariantColourEntry[]>;
  /** How variant_colour_map was resolved: "roster" | "cyclic" | "web" | "fallback" */
  variant_colour_source?: string;
  /** Parts with different part numbers per colour (same ref_no, ≥2 colours). */
  colour_changing_parts?: ColourChangingPart[];
}

export const fetchAgentBuilds = (rel_path: string, refresh = false) =>
  api.get<AgentResult>(
    `/catalog/agent/${rel_path.split("/").map(encodeURIComponent).join("/")}${refresh ? "?refresh=true" : ""}`,
    { timeout: 180_000 },
  ).then(r => r.data);

export const clearAgentCache = (rel_path: string) =>
  api.delete(
    `/catalog/agent/${rel_path.split("/").map(encodeURIComponent).join("/")}`,
  );

export const clearAllAgentCache = () =>
  api.delete<{ deleted: number }>("/catalog/agent-cache/all").then(r => r.data);

export interface ExtractionStatus {
  running: boolean;
  last_result: {
    ok: boolean; total_rows?: number; distinct_parts?: number;
    models?: number; parquet?: string; excel?: string | null; error?: string;
  } | null;
  parquet_exists: boolean;
  parquet_size_kb: number;
  excel_exists: boolean;
}

export const downloadCatalogExcelUrl = () => `/api/v1/catalog/download`;
export const fetchExtractionStatus = () =>
  api.get<ExtractionStatus>("/catalog/extraction-status").then(r => r.data);
export const runBatchExtraction = () =>
  api.post<{ queued: boolean; message: string }>("/catalog/run-extraction").then(r => r.data);

// ── Source refresh (src/refresh.py) ────────────────────────────────────────────
export interface RefreshStatus {
  state: "idle" | "checking" | "running" | "done" | "failed";
  reason?: string;
  changed?: string[];
  stages?: string[];
  stage?: string | null;
  position?: number;
  total?: number;
  as_of?: string;
  started_at?: string;
  finished_at?: string;
  error?: string | null;
  failed_stages?: string[];
  waiting_for?: string[];
  notes?: string[];
  report?: string;
}
export const fetchRefreshStatus = () =>
  api.get<RefreshStatus>("/pipeline/refresh-status").then(r => r.data);
export const startRefresh = (rerunAll = false) =>
  api.post<RefreshStatus & { started: boolean }>(`/pipeline/refresh?rerun_all=${rerunAll}`).then(r => r.data);

// ── Catalogue database (PostgreSQL) ────────────────────────────────────────────
export interface CatalogueDbStatus {
  reachable: boolean;
  error?: string;
  on_disk: number;
  loaded?: number;
  excluded?: Record<string, string>;
  not_loaded?: string[];
  /** PN_Yamaha (Brand YM) materials loaded, and how many matched a catalogue part. */
  pn_yamaha?: { rows: number; matched: number; loaded_at: string | null };
}
export interface CatalogueDbLoadStatus {
  running: boolean;
  force?: boolean;
  total: number;
  done?: number;
  loaded?: number;
  skipped?: number;
  excluded?: number;
  failed?: { source_file: string; error: string }[];
  current?: string | null;
  error?: string | null;
  started_at?: string;
  finished_at?: string | null;
  pn_yamaha?: { loaded: number; brand_rows: number; source_rows: number };
}
export const fetchCatalogueDbStatus = () =>
  api.get<CatalogueDbStatus>("/catalog/db/status").then(r => r.data);
export const fetchCatalogueDbLoadStatus = () =>
  api.get<CatalogueDbLoadStatus>("/catalog/db/load-status").then(r => r.data);
export const loadAllCataloguesToDb = (force = false) =>
  api.post<{ queued: boolean; message?: string; total?: number }>(
    `/catalog/db/load-all?force=${force}`,
  ).then(r => r.data);

export const fetchCatalogFolders = () =>
  api.get<string[]>("/catalog/folders").then(r => r.data);

export const uploadCatalogPdf = (file: File, folder: string) => {
  const form = new FormData();
  form.append("file", file);
  form.append("folder", folder);
  return api.post<{ rel_path: string; filename: string; folder: string }>(
    "/catalog/upload", form,
    { headers: { "Content-Type": "multipart/form-data" }, timeout: 60_000 },
  ).then(r => r.data);
};

export interface ExcelCatalogueFile { filename: string; stem: string; size_kb: number; }
export interface ExcelCatalogueData {
  filename: string;
  headers: string[];
  rows: string[][];
  total: number;
  sections: string[];
}
export const fetchExcelCatalogues = () =>
  api.get<ExcelCatalogueFile[]>("/catalog/excel").then(r => r.data);
export const fetchExcelCatalogue = (filename: string, section?: string, search?: string) =>
  api.get<ExcelCatalogueData>(`/catalog/excel/${encodeURIComponent(filename)}`, {
    params: { ...(section ? { section } : {}), ...(search ? { search } : {}) },
  }).then(r => r.data);

export interface CatalogCoverageRow { model: string; pdf_count: number; distinct_parts: number; ocr_pages: number; }
export interface CatalogCoverageData {
  extracted: boolean; total_part_references: number;
  distinct_parts: number; distinct_models: number;
  rows: CatalogCoverageRow[];
}
export interface CatalogPartRow { part_number: string; source_file: string; ocr_used: boolean; }
export const fetchCatalogCoverage = () => api.get<CatalogCoverageData>("/catalog/coverage").then(r => r.data);
export const fetchCatalogParts = (model: string, limit = 500) =>
  api.get<CatalogPartRow[]>(`/catalog/parts/${encodeURIComponent(model)}`, { params: { limit } }).then(r => r.data);

export type DealerType = "MC" | "OBM" | "ALL";
export type McCategoryType = "ALL" | "Lubricant" | "Battery" | "Tyre" | "SpareParts";

export const fetchOrdersEda = (dealerType: DealerType = "MC", mcCategory: McCategoryType = "ALL", year: number = 0) =>
  api.get<OrdersEdaData>("/eda/orders", { params: { dealer_type: dealerType, mc_category: mcCategory, year }, timeout: 90_000 }).then(r => r.data);
export const fetchSalesEda    = (dealerType: DealerType = "MC", mcCategory: string = "ALL", year: number = 0) =>
  api.get<SalesEdaData>("/eda/sales", { params: { dealer_type: dealerType, mc_category: mcCategory, year }, timeout: 60_000 }).then(r => r.data);
export const fetchMovements   = () => api.get<MovementsData>("/eda/movements").then(r => r.data);
export const fetchSparePartsEda = () => api.get<SparePartsEdaData>("/eda/spare-parts").then(r => r.data);
export interface AssociationRule {
  antecedents: string[];
  consequents: string[];
  support: number;
  confidence: number;
  lift: number;
  conviction: number | null;
  antecedent_support: number;
  consequent_support: number;
}
export interface FrequentItemset {
  items: string[];
  support: number;
  count: number;
}
export interface CoOccurrenceGroup {
  items: string[];
  count: number;
  support: number;
  lift: number;
}
export interface LargeInvoice {
  billing_document: string;
  billing_date: string;
  payer: string;
  items: string[];
  item_count: number;
}
export interface MarketBasketData {
  total_baskets: number;
  multi_item_baskets: number;
  total_unique_materials: number;
  total_rules: number;
  max_basket_size: number;
  top_materials: { material: string; count: number; support: number }[];
  frequent_itemsets: FrequentItemset[];
  rules: AssociationRule[];
  groups: CoOccurrenceGroup[];
  large_invoices: LargeInvoice[];
}
export const fetchMarketBasket = (
  min_support = 0.01,
  min_confidence = 0.05,
  min_lift = 1.0,
) =>
  api
    .get<MarketBasketData>("/eda/market-basket", {
      params: { min_support, min_confidence, min_lift },
      timeout: 90_000,
    })
    .then(r => r.data);

// ── ML Market Basket ──────────────────────────────────────────────────────────
export interface ItemSimilarity {
  item: string;
  score: number;
  method: string;
}
export interface ItemRecommendation {
  item: string;
  freq: number;
  item2vec: ItemSimilarity[];
  svd: ItemSimilarity[];
}
export interface CustomerRecommendation {
  payer: string;
  purchased: string[];
  recommendations: { item: string; score: number }[];
}
export interface UmapPoint {
  item: string;
  x: number;
  y: number;
  cluster: number;
  freq: number;
}
export interface MLCluster {
  cluster_id: number;
  items: string[];
  count: number;
}
export interface MarketBasketMLData {
  item_recommendations: ItemRecommendation[];
  customer_recommendations: CustomerRecommendation[];
  umap_coords: UmapPoint[];
  clusters: MLCluster[];
  model_info: {
    embedding_dim: number;
    n_baskets: number;
    n_items_trained: number;
    n_components_svd: number;
    n_clusters: number;
  };
}
export const fetchMarketBasketML = () =>
  api
    .get<MarketBasketMLData>("/eda/market-basket/ml", { timeout: 120_000 })
    .then(r => r.data);

// ── Module 6: Purchase Recommendation ────────────────────────────────────────

export interface PurchaseRecommendationSummary {
  total_skus_to_order: number;
  critical_count: number;
  high_count: number;
  stockout_risk_count: number;
  overstock_count: number;
  weighted_fill_rate_pct: number;
  container_utilization_pct: number;
}

export interface PurchaseRecommendationRow {
  part_no: string;
  order_qty: number;
  priority: number;
  urgency_score: number;
  demand_class: string;
  abc: string;
  mean_monthly_demand: number;
  binding_constraint: string;
  risk_level: string;
  action: string;
  fill_rate_pct: number;
}

export interface PurchaseRecommendationResponse {
  total: number;
  offset: number;
  limit: number;
  rows: PurchaseRecommendationRow[];
}

export interface StockoutRiskRow {
  part_no: string;
  risk_pct: number;
  days_until_stockout: number;
  urgency_score: number;
}

export interface OverstockRow {
  part_no: string;
  excess_qty: number;
  months_cover: number;
  demand_class: string;
}

export interface FillRateRow {
  part_no: string;
  fill_rate_pct: number;
  stock_qty: number;
  monthly_demand: number;
}

export const fetchPurchaseRecommendationSummary = () =>
  api
    .get<PurchaseRecommendationSummary>("/purchase-recommendation/summary")
    .then(r => r.data);

export const fetchPurchaseRecommendations = (params?: Record<string, unknown>) =>
  api
    .get<PurchaseRecommendationResponse>("/purchase-recommendation/recommendations", { params })
    .then(r => r.data);

export const fetchStockoutRisk = (params?: Record<string, unknown>) =>
  api
    .get<{ total: number; rows: StockoutRiskRow[] }>(
      "/purchase-recommendation/stockout-risk",
      { params },
    )
    .then(r => r.data);

export const fetchOverstockRisk = (params?: Record<string, unknown>) =>
  api
    .get<{ total: number; rows: OverstockRow[] }>(
      "/purchase-recommendation/overstock",
      { params },
    )
    .then(r => r.data);

export const fetchFillRate = (params?: Record<string, unknown>) =>
  api
    .get<{ total: number; rows: FillRateRow[] }>(
      "/purchase-recommendation/fill-rate",
      { params },
    )
    .then(r => r.data);

// ── Module 1 — Vehicle Intelligence ──────────────────────────────────────────

export interface M1SalesForecastRow {
  month: string;
  model: string;
  forecast_units: number;
  lower_ci: number;
  upper_ci: number;
}
export interface M1SalesForecastResponse {
  total: number;
  rows: M1SalesForecastRow[];
  models: string[];
}
export const fetchM1SalesForecast = (params?: Record<string, unknown>) =>
  api.get<M1SalesForecastResponse>("/bikes/sales-forecast", { params }).then(r => r.data);

export interface M1UIOForecastRow {
  month: string;
  model: string;
  uio_forecast: number;
}
export interface M1UIOForecastResponse {
  total: number;
  rows: M1UIOForecastRow[];
  models: string[];
}
export const fetchM1UIOForecast = (params?: Record<string, unknown>) =>
  api.get<M1UIOForecastResponse>("/bikes/uio-forecast-m1", { params }).then(r => r.data);

export interface M1AgeDistRow {
  model: string;
  age_cohort: string;
  vehicle_count: number;
  pct_of_fleet: number;
}
export interface M1AgeDistResponse {
  total: number;
  rows: M1AgeDistRow[];
}
export const fetchM1AgeDist = () =>
  api.get<M1AgeDistResponse>("/bikes/age-distribution").then(r => r.data);

// ── Module 2 — Demand Intelligence ───────────────────────────────────────────

export interface M2FusedDemandRow {
  part_no: string;
  month: string;
  demand_qty: number;
  method: string;
  cv: number | null;
  demand_class: string;
}
export interface M2FusedDemandResponse {
  total: number;
  offset: number;
  limit: number;
  rows: M2FusedDemandRow[];
  method_counts: Record<string, number>;
  demand_class_counts: Record<string, number>;
}
export const fetchFusedDemand = (params?: Record<string, unknown>) =>
  api.get<M2FusedDemandResponse>("/forecast/fused-demand", { params }).then(r => r.data);

export interface M2OrdersForecastRow {
  part_no: string;
  month: string;
  forecast_qty: number;
  source: string;
}
export interface M2OrdersForecastResponse {
  total: number;
  offset: number;
  limit: number;
  rows: M2OrdersForecastRow[];
  source_counts: Record<string, number>;
}
export const fetchOrdersForecast = (params?: Record<string, unknown>) =>
  api.get<M2OrdersForecastResponse>("/forecast/orders-forecast", { params }).then(r => r.data);

export interface M2UIODemandModuleRow {
  part_no: string;
  month: string;
  uio_demand_qty: number;
  source: string;
}
export interface M2UIODemandModuleResponse {
  total: number;
  offset: number;
  limit: number;
  rows: M2UIODemandModuleRow[];
}
export const fetchM2UIODemand = (params?: Record<string, unknown>) =>
  api.get<M2UIODemandModuleResponse>("/forecast/uio-demand", { params }).then(r => r.data);

// ── Module 3 — Inventory Intelligence ────────────────────────────────────────

export interface M3InvPositionRow {
  part_no: string;
  stock_qty: number;
  pipeline_qty: number;
  backorder_qty: number;
  net_position: number;
}
export interface M3InvPositionResponse {
  total: number;
  offset: number;
  limit: number;
  rows: M3InvPositionRow[];
  total_stock_qty: number;
  total_pipeline_qty: number;
  total_net_position: number;
}
export const fetchInventoryPosition = (params?: Record<string, unknown>) =>
  api.get<M3InvPositionResponse>("/inventory/position", { params }).then(r => r.data);

// ── Module 4 — Inventory Planning ────────────────────────────────────────────

export interface M4PlanningRow {
  part_no: string;
  demand_class: string;
  mean_monthly_demand: number;
  lead_time_demand: number;
  review_demand: number;
  horizon_demand: number;
  sigma_demand: number;
  service_level: number;
  z_score: number;
  ss_method: string;
  safety_stock: number;
  rol: number;
  stock_qty: number;
  pipeline_qty: number;
  backorder_qty: number;
  net_position: number;
  signal_to_reorder: boolean;
  urgency_score: number;
}
export interface M4PlanningResponse {
  total: number;
  offset: number;
  limit: number;
  rows: M4PlanningRow[];
  signal_count: number;
  demand_class_counts: Record<string, number>;
}
export const fetchPlanningTable = (params?: Record<string, unknown>) =>
  api.get<M4PlanningResponse>("/classification/planning-table", { params }).then(r => r.data);

export const fetchInventoryPlanning = (params?: Record<string, unknown>) =>
  api.get<M4PlanningResponse>("/inventory/planning", { params }).then(r => r.data);

export interface M4SafetyStockRow {
  part_no: string;
  safety_stock: number;
  service_level: number;
  z_score: number;
  sigma_demand: number;
  demand_class: string;
  ss_method: string;
}
export interface M4SafetyStockResponse {
  total: number;
  offset: number;
  limit: number;
  rows: M4SafetyStockRow[];
  demand_class_counts: Record<string, number>;
}
export const fetchSafetyStock = (params?: Record<string, unknown>) =>
  api.get<M4SafetyStockResponse>("/inventory/safety-stock", { params }).then(r => r.data);
