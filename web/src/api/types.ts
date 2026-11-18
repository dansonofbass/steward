// Mirrors the JSON the API returns (src/steward/api/*.py). Money is integer cents; dates are ISO strings.

export type Owner = string;
export type Kind = 'household' | 'parent';
export type Role = 'manager' | 'viewer';
export type OwnerOption = { key: string; label: string };
export type AccountType =
  | 'unknown' | 'checking' | 'savings' | 'credit' | 'brokerage_taxable' | 'k401' | 'roth_ira'
  | 'traditional_ira' | 'hsa' | 'plan529' | 'mortgage' | 'property' | 'loan' | 'business_checking' | 'business_credit' | 'vehicle';
export type Source = 'simplefin' | 'manual';

export type UserBrief = { id: number; username: string; display_name: string };
export type { ProfileMarks } from './profile';
import type { ProfileMarks } from './profile';
export type BookSummary = {
  slug: string; name: string; kind: Kind; role: Role; available: boolean;
  /** Why the book can't be opened, for managers only (spec 8). */
  reason: string | null;
  owners: OwnerOption[];
  /** Profile marks: household books the person manages only. */
  profile: ProfileMarks | null;
  /** Chat is on in this book (plan B ruling 26); absent means off. */
  chat?: boolean;
  /** A Sample book (guided setup spec 11): made-up money, nothing leaves it. */
  sample?: boolean;
  /** The welcome this person has yet to see here: their first run, or a partner's (spec 2, D4); null once seen. */
  welcome?: 'first_run' | 'partner' | null;
  /** This person can manage the install (Get Steward ready is theirs). */
  install?: boolean;
};
export type Member = { user_id: number; username: string; display_name: string; email?: string; role: Role };   // email: managers only
/** A manager also gets the people invited who have not joined: the typed email, a role and an invite id, no name. */
export type InvitedRow = { status: 'Invited'; invite_id: string; email: string; role: Role; user_id: null; username: null; display_name: null };
export type MemberList = { members: (Member | InvitedRow)[] };
export type Me = {
  user: UserBrief & { email: string | null; prefs?: { celebrations: boolean | null; sound: boolean | null } };
  books: BookSummary[];
  session: { id: number; device_label: string; created_at: string };
  gateway_name?: string;   // spec 2026-11-05, section 7; absent in fixtures: "the gateway"
  timezone?: string;       // the household's zone (issue #26, lib/today.ts); absent in fixtures: the device's
};
export type Session = { id: number; device_label: string; created_at: string; last_seen_at: string };
export type SessionList = { sessions: Session[] };
export type UserRow = UserBrief & { email?: string; can_reset: boolean };   // email: yours, and people in books you manage
export type UserList = { users: UserRow[] };
export type Passkey = { id: number; label: string; created_at: string };
export type PasskeyList = { passkeys: Passkey[] };

export type Account = {
  id: number;
  name: string;
  type: AccountType;
  owner: Owner;
  /** The owner in words, a member's name or a role (issue #31). */
  owner_label?: string;
  source: Source;
  institution: string;
  is_active: boolean;
  rate_bp?: number | null;
  /** An investment account's adviser fee in basis points (investment views spec). */
  advisory_fee_bp?: number | null;
  /** A vehicle's loan account, for display. */
  loan_id?: number | null;
  balance_cents: number | null;
  as_of: string | null;
  stale_days: number | null;
};
export type AccountList = { accounts: Account[] };

export type Institution = {
  id: number;
  name: string;
  source: Source;
  last_sync_at: string | null;
  last_error: string | null;
  account_count: number;
};
export type InstitutionList = { institutions: Institution[] };

export type FactValue = { value: string; as_of: string; note: string | null };
export type Facts = { facts: Record<string, FactValue> };

export type Txn = {
  id: number;
  account_id: number;
  account_name: string;
  posted_at: string;
  amount_cents: number;
  raw_description: string;
  merchant: string | null;
  /** Polish round P31: the name a person gave the row, shown "Disney+ (PayPal)". */
  nickname?: string | null;
  category: string;
  is_business: boolean;
  is_transfer: boolean;
  business_pct: number;
  business_line: string | null;
  business_source: 'none' | 'manual' | 'rule' | 'account';
  category_source: 'rule' | 'correction' | 'model' | 'none';
  reviewed_at: string | null;
  from_bank: boolean;
  /** Phase 11c: the set-aside this payment is matched to; the API always sends it, older fixtures leave it out. */
  set_aside?: { id: number; name: string; how: 'auto' | 'hand'; archived: boolean } | null;
  /** Phase 12: notes on the row (lists), why it is in Review and the model's guess (Review only). */
  note_count?: number;
  reason?: 'p2p' | 'unsure' | 'unknown' | 'waiting' | 'no_rule';
  guess?: string | null;
  /** Sorting redesign: how many other rows a rule for this description would reach (Review only); null when none can be made. */
  matching?: number | null;
  /** Reimbursable spec: the payer of a reimbursable charge or of a repayment, the trip it was marked on, and (household
   *  lists, Review and the PATCH reply) whether the Reimbursable switch is offered. */
  reimburser_id?: number | null;
  trip_id?: number | null;
  reimburse_ok?: boolean;
};
export type TxnPage = { transactions: Txn[]; next_cursor: string | null };
export type TxnPatchReply = Txn & { result?: SortResult };
export type SortResult = {
  category: string; applied: number; rule: 'made' | 'changed' | 'kept' | 'none'; undo: string;
  /** Review focus P22: the rows the spread changed. Optional: an older server leaves it out, and the next refetch
   *  removes those cards instead. */
  ids?: number[];
  reimburse?: ReimburseChange | null;
};
export type SnoozeReply = { undo: string; until: string };
export type IgnoreReply = { undo: string };
export type UndoReply = { undone: number; transaction: Txn | null };
/** Bulk sort (profile spec, Sorting several rows at once): POST /transactions/sort. `undo` is null when nothing was sorted. */
export type SortManyReply = { sorted: number; ids: number[]; category: string; skipped: { id: number; reason: string }[]; undo: string | null };
/** Reimbursable expenses (reimbursable spec). */
export type Payer = { id: number; name: string };
export type PayerList = { payers: Payer[] };
/** What a sort or the switch did to a payer's balance: the receipt's facts (engineering choice 10). */
export type ReimburseChange = {
  change: 'marked' | 'unmarked' | 'repaid'; reimburser_id: number; payer: string; was_cents: number; owed_cents: number;
};
export type PayerBalance = Payer & {
  owed_cents: number; marked_cents: number; repaid_cents: number; refunds_cents: number; settled_cents: number;
  cleared_cents: number; since: string | null; last_repaid_on: string | null; settle_category: string;
};
export type ItemStatus = 'waiting' | 'partly' | 'paid';
export type TripSummary = {
  id: number; name: string; start: string; end: string; city: string | null; reimburser_id: number; payer: string;
  count: number; total_cents: number; status: ItemStatus | null;
};
export type Reimbursements = { as_of: string; payers: PayerBalance[]; trips: TripSummary[]; singles: (Txn & { status: ItemStatus })[] };
export type TripReason = {
  why: 'booked' | 'says' | 'flight' | 'hotel' | 'travel' | 'ride' | 'new' | 'regular' | 'home_only' | 'unsure' | 'refund';
  place?: string; category?: string;
};
export type TripRow = Omit<Txn, 'reason'> & { group: 'booked' | 'likely' | 'home' | 'unsure'; reason: TripReason; ticked: boolean };
export type TripDetail = { trip: TripSummary; rows: TripRow[] };
export type TripBody = { name: string; start: string; end: string; city: string | null; reimburser_id?: number };
export type TripMarkReply = { count: number; total_cents: number; payer: string; owed_cents: number; undo: string; trip: TripSummary };
export type SettleReply = { owed_cents: number; settled_cents: number; category: string; month: string; undo: string };
export type RuleMarkReply = { rule: { id: number; pattern: string; reimburser_id: number }; also_marked: number; undo: string };
/** expected: a categorizer is coming (a paired gateway not known to lack its model). False: rows just wait in Review (INS-21). */
export type Background = { pending: number; done: number; waiting: boolean; expected?: boolean };

export type ReviewQueue = {
  uncategorized: Txn[];
  count: number;
  duplicates: { a: Txn; b: Txn }[];
  duplicate_count: number;
  top_categories: string[];
  business: Txn[];
  business_count: number;
  sorted_count?: number;
  /** Phase 17: the book has no transactions at all (Review says so instead of All caught up). An older server leaves it out. */
  empty?: boolean;
  background?: Background;
};
export type BusinessRule = { id: number; kind: 'merchant' | 'client' | 'account'; label: string; account_id: number | null; account_name: string | null; pct: number; line: string | null };
export type RuleReply = { rule: BusinessRule; also_tagged: number };

export type SplitKey = 'investable' | 'home_and_cars' | 'owed' | 'business' | 'unset';
export type Summary = {
  net_worth_cents: number;
  month_start: string;
  change_month_cents: number | null;
  /** Investment views spec: net worth now less on Dec 31; null without a balance from before Jan 1. */
  year_start: string;
  change_year_cents: number | null;
  /** The split: Investable, Home and cars, What you owe, Business and Type not set yet, with each line's accounts. */
  split: Record<SplitKey, { cents: number; account_ids: number[] }>;
  as_of: string;
  accounts_by_type: Partial<Record<AccountType, number>>;
  needs_attention: { id: number; message: string; kind: string }[];
};
export type HistoryPoint = { date: string; net_worth_cents: number; investable_cents?: number };
export type History = { points: HistoryPoint[] };

export type Event = {
  id: number;
  at: string;
  level: string;
  kind: string;
  message: string;
  actionable: boolean;
  resolved_at: string | null;
};
export type EventList = { events: Event[] };

/** sign_in: the banks whose open warning on Home says to sign in again at SimpleFIN (issue #16). */
export type SimplefinStatus = { linked: boolean; last_sync_at: string | null; last_error: string | null; sign_in?: string[] };
export type SyncResult = {
  institutions_ok: number;
  institutions_failed: number;
  accounts_new: number;
  transactions_new: number;
  errors: string[];
};
export type LinkResult = { linked: true; sync: SyncResult | null };

/** GET /api/spending/flow, Home's strip: each month's money out and income by Spending's rules. */
export type FlowMonth = { month: string; in_cents: number; out_cents: number; net_cents: number };
export type SpendingFlow = { as_of: string; months: FlowMonth[] };

/** What Home needs from GET /api/plan; the Plan tab reads the same cache entry with its full type. */
export type HomePlan = { setup: unknown[] } | { plan: { id: number } | null; result: { comfortable_age: number | null } };

/** GET /api/b/<slug>/flags/count: open plus Still checking, and whether any of them is urgent (decision 5). */
export type FlagCount = { count: number; urgent: boolean };

export type BusinessType = 'none' | 'sole_prop' | 's_corp';
export type ReportLine = { key: string; number: string; label: string; spent_cents: number; counts_cents: number; count: number; note: string | null };
/** Schedule C profit (low, high, mid) for tax, and cash profit (cash_*) for the plan (final review ruling I3). */
export type ProfitRangeOut = {
  year: number; ytd_cents: number; low_cents: number; high_cents: number; mid_cents: number; entered: boolean;
  cash_ytd_cents: number; cash_low_cents: number; cash_high_cents: number; cash_mid_cents: number; ask_expect: boolean;
};
export type BusinessReport = {
  year: number; this_year: number; through: string; type: BusinessType; income_cents: number; expenses_cents: number; profit_cents: number;
  lines: ReportLine[]; range: ProfitRangeOut; left_out: number; using_note: string | null; home_office_limited: boolean;
};
export type LineDetail = { line: { key: string; number: string; label: string }; transactions: (Txn & { share_cents: number })[] };

export type ScorpPoint = { label: 'low' | 'middle' | 'high' | 'so far'; profit_cents: number; salary_cents: number; sole_tax_cents: number; scorp_tax_cents: number; cost_cents: number; saves_cents: number; payroll_cents: number; franchise_cents: number; sdi_cents: number; unemployment_cents: number };
export type ScorpOut = { available: true; year: number; line: string; worth_it: boolean; salary_pct: number; cost_cents: number; rules_note: string; state_note: string; points: ScorpPoint[] } | { available: false; reason: string };

// Spending (phase 11b): GET /api/spending, /api/spending/trends, /api/spending/targets; PUT /api/spending/targets.
export type SpendingKind = 'everyday' | 'fixed' | 'commitment' | 'occasional';
export type PaceState = 'on_track' | 'over' | 'none';
export type OverLevel = 'on' | 'little' | 'clear';
export type FixedState = 'waiting' | 'late' | 'so_far' | 'under' | 'as_usual' | 'over' | 'none';
/** check: paid, in neutral ink; ring: dashed, muted; amber: a Bill's only; quiet: no icon. */
export type FixedTone = 'check' | 'ring' | 'amber' | 'quiet';
export type FixedSummary = 'none' | 'to_come' | 'more' | 'plain';
export type EverydayRow = {
  category: string; kind: 'everyday'; target_cents: number | null; spent_cents: number; refunds_cents: number;
  usual_by_today_cents: number | null; state: PaceState; over_cents: number | null; over_level: OverLevel | null; typical_cents: number | null; order: number;
};
/** A Bill (kind fixed) or a Commitment. expected: paid in 4 of the last 6 months, or set above $0 (P4);
 *  expected_cents is usual when expected, else null. new_payee is a Bill's only. outside_cents is on Giving's row only. */
export type FixedRow = {
  category: string; kind: 'fixed' | 'commitment'; expected: boolean; expected_cents: number | null; usual_cents: number | null;
  spent_cents: number; refunds_cents: number; state: FixedState; tone: FixedTone; came_out_on: string | null;
  merchant: string | null; typical_day: number | null; new_payee: { name: string; cents: number } | null; outside_cents?: number;
};
export type OccasionalRow = { category: string; kind: 'occasional'; spent_cents: number; paid_on: string | null };
export type IncomeRow = { category: string; cents: number };
export type SpendingHead = {
  spent_cents: number; planned_cents: number; everyday_spent_cents: number; everyday_target_cents: number;
  fixed_spent_cents: number; fixed_expected_cents: number; fixed_more_cents: number; fixed_not_yet: number;
  fixed_summary: FixedSummary; occasional_cents: number; money_out_cents: number; income_cents: number;
  /** Home's money in for the month (Spending's rules): income, plus money in that takes a category past $0. */
  money_in_cents: number;
  set_aside_cents: number; paid_from_set_aside_cents: number;
};
/** P19: the one Flexible target the monthly check asks about (the current month only). */
export type TargetCheck = { category: string; target_cents: number; typical_cents: number };
/** P20: a target someone kept, until the first of that month. */
export type KeptTarget = { category: string; target_cents: number; until: string };
export type SpendingMonth = {
  month: string; as_of: string; current: boolean; day: number | null; days: number; days_left: number | null;
  earliest: string | null; head: SpendingHead; everyday: EverydayRow[]; not_sorted: { count: number; cents: number };
  fixed: FixedRow[]; occasional: OccasionalRow[]; income: IncomeRow[]; target_check: TargetCheck | null; has_targets: boolean;
  set_aside: SpendingSetAside | null; kinds: Record<string, SpendingKind>;
};
// unjudged: a fixed cost with no history or nothing expected (ruling 24). Over time draws and names none of them; its
// category page still draws its months.
export type TrendGroup = 'everyday' | 'fixed' | 'steady' | 'unjudged' | 'occasional';
export type TrendRow = {
  category: string; kind: SpendingKind; group: TrendGroup; target_cents: number | null; expected_cents: number | null;
  typical_cents: number | null; spent: number[]; over_in: number; over_of: number; order: number;
};
export type SpendingTrends = { as_of: string; months: string[]; current: string; categories: TrendRow[] };
export type TargetRow = {
  category: string; kind: SpendingKind; monthly_cents: number | null; typical_cents: number | null; usual_cents: number | null;
  suggested_cents: number | null; low_cents: number | null; high_cents: number | null; order: number;
};
export type SpendingTargets = {
  as_of: string; categories: TargetRow[]; kept: KeptTarget[]; updated_at: string | null; updated_by: string | null;
  has_targets: boolean; typical_income_cents: number | null;
};
export type TargetChange = { category: string; kind: SpendingKind; monthly_cents: number | null };
export type TargetsBody = { targets: TargetChange[] };

// Set-asides (phase 11c): GET /api/setasides, /api/setasides/{id}; the writes are in api/setasides.ts. The web shows
// these figures and dates as the server sends them and works out none of its own.
export type SetAsideKind = 'yearly' | 'twice_yearly' | 'one_off';
export type SetAsideState = 'short' | 'behind' | 'not_paid' | 'on_track' | 'no_account';
/** as_of is the balance snapshot's date; stale means older than 7 days (the page says "balance from Oct 12"). */
export type SetAsideAccount = { id: number; name: string; balance_cents: number | null; as_of: string | null; stale: boolean; shared_with: string[] };
/** The stored basis of an estimated one-off. to_check: the lifespan is unverified; cost_to_check: the cost range is. */
export type SetAsideEstimate = {
  item: string; installed_year: number | null; model_year: number | null; miles: number | null; lifespan: [number, number];
  cost_range: [number, number]; planned_year: number; replacement_cents: number; sale_cents: number; confirmed: boolean;
  to_check: boolean; cost_to_check: boolean;
};
export type SetAsidePaid = { transaction_id: number; posted_at: string; cents: number; account_name: string };
export type SetAsideRow = {
  id: number; name: string; kind: SetAsideKind; amount_cents: number; monthly_cents: number; yearly_cents: number; installment_cents: number;
  due_month: number | null; due_day: number | null; second_month: number | null; second_day: number | null; due_year: number | null;
  first_month: string; next_due: string | null; days_until: number | null; missed_due: string | null; is_estimate: boolean;
  estimate: SetAsideEstimate | null; account: SetAsideAccount | null; put_away_cents: number; should_cents: number; state: SetAsideState;
  short_cents: number; behind_cents: number; counted_from: string | null; payee_key: string | null; payee_name: string | null;
  category: string | null; notes: string | null; paid: SetAsidePaid | null; archived_at: string | null;
};
export type DueStatus = 'missed' | 'paid' | 'late' | 'skipped' | 'next' | 'upcoming';
export type SetAsideDue = { due_on: string; status: DueStatus; which: 'first' | 'second' | null; amount_cents: number; paid_on: string | null; days_late: number | null; days_until: number };
export type SetAsidePayment = {
  transaction_id: number; posted_at: string; account_name: string; merchant: string | null; nickname?: string | null; raw_description: string; category: string;
  amount_cents: number; due_on: string; how: 'auto' | 'hand'; late: boolean; days_late: number;
};
/** An estimate worked out by the server. sources holds only this item's own (lifespan, then cost); to_check and cost_to_check
 *  say which of the two is unverified, and an unverified figure is never shown as sourced. */
export type EstimateOut = {
  item: string; label: string; installed_year: number | null; model_year: number | null; miles: number | null; age: number;
  miles_per_year: number | null; lifespan: [number, number]; lifespan_miles: [number, number] | null; range: [number, number];
  decided_by: 'age' | 'miles'; planned_year: number; due_year: number; due_month: number; cost_range: [number, number];
  replacement_cents: number; sale_cents: number; amount_cents: number; months: number; first_month: string; monthly_cents: number; sources: string[];
  to_check: boolean; cost_to_check: boolean;
};
/** POST /setasides/estimate: a bare estimate (no kind), or any draft: its monthly amount, first month, next due date and the
 *  months it is spread over, plus should_cents for an edit and is_estimate for an estimated one-off. */
export type EstimatePreview = Omit<Partial<EstimateOut>, 'months'> & {
  amount_cents: number; monthly_cents: number; first_month: string; next_due: string | null; months: number | null;
  kind?: SetAsideKind; yearly_cents?: number; should_cents?: number; is_estimate?: boolean; estimate?: SetAsideEstimate;
};
export type SetAsideReplace = { paid_on: string; paid_cents: number; next: EstimateOut | null };
/** What replacing a paid one-off would set aside: the next one's year, cost and monthly amount. */
export type SetAsideReplaceOffer = { year: number; cents: number; monthly_cents: number };
/** The stored basis with its evidence: the item's own sources (lifespan, then cost) and its age, from the server. */
export type SetAsideDetailEstimate = SetAsideEstimate & { sources?: string[]; age?: number | null };
/** as_of is the server's today. find_from/find_to are the range "Find the payment" looks in (null when no installment is missed). */
export type SetAsideDetail = Omit<SetAsideRow, 'estimate'> & {
  as_of: string; estimate: SetAsideDetailEstimate | null; dues: SetAsideDue[]; payments: SetAsidePayment[];
  replace: SetAsideReplace | null; replace_offer: SetAsideReplaceOffer | null; find_from: string | null; find_to: string | null;
};
export type SetAsideGroup = 'home' | 'car' | 'kids' | 'memberships' | 'other';
/** A true yearly or twice-yearly cost (polish round, item 3): its clean name, group and months, and a year's amount.
 *  The server merges payees with the same name and category and keeps the newest payment's payee key. */
export type SetAsideSuggestion = {
  key: string; name: string; group: SetAsideGroup; kind: 'yearly' | 'twice_yearly'; amount_cents: number; yearly_cents: number;
  monthly_cents: number; months: number[]; payee_key: string; category: string; due_month: number; due_day: number;
  second_month: number | null; second_day: number | null; payments: string[];
};
export type SetAsideDismissed = { payee_key: string; payee_name: string; category: string; monthly_cents: number };
export type SetAsideList = {
  as_of: string; monthly_cents: number; count: number; yearly_cents: number; one_off_cents: number; needs_look: number;
  rows: SetAsideRow[]; suggestions: SetAsideSuggestion[]; dismissed: SetAsideDismissed[]; history_months: number; first_visit: boolean;
};
export type EstimateIn = { item: string; installed_year?: number | null; model_year?: number | null; miles?: number | null };
export type SetAsideBody = {
  name: string; kind: SetAsideKind; amount_cents: number; due_month?: number | null; due_day?: number | null; second_month?: number | null;
  second_day?: number | null; due_year?: number | null; account_id?: number | null; payee_key?: string | null; category?: string | null;
  estimate?: EstimateIn | null; notes?: string | null;
};
/** What the preview takes: a bare estimate's inputs, or a draft (any of the body's fields); set_aside_id previews an edit. */
export type PreviewIn = Partial<SetAsideBody> & Partial<EstimateIn> & { set_aside_id?: number };
export type SpendingPaid = { set_aside_id: number; name: string; transaction_id: number; payee: string; posted_at: string; cents: number; late: boolean; account_name: string; category: string; archived: boolean };
export type SpendingSetAside = {
  monthly_cents: number; count: number; yearly_cents: number; one_off_cents: number; names: string[]; needs_look: SetAsideRow[];
  paid: SpendingPaid[]; next: { name: string; next_due: string } | null;
};

export type Note = { id: number; author_id: number; author_name: string; body: string; created_at: string };
export type NoteList = { notes: Note[] };

export type CategoryRule = { id: number; pattern: string; merchant: string | null; category: string | null; rows: number; created_at: string; amount_cents: number | null; nickname: string | null; has_note: boolean };

/** GET /transactions/{tid}/label (polish round, item 5): the row's name, how far "Also…" reaches (null when no rule can
 *  be made), and the rule "And future ones" keeps the label on. */
export type LabelView = {
  nickname: string | null;
  reach: { others: number; payee: string; amount_cents: number | null; generic: boolean } | null;
  rule: { id: number; nickname: string | null; note: string | null; has_category: boolean } | null;
};
export type LabelBody = { note: string | null; nickname: string | null; also: boolean; future: boolean };
export type LabelReply = { rows: number; notes_added: number; named: number; rule_id: number | null; undo: string };
export type CategoryRuleList = { rules: CategoryRule[] };
