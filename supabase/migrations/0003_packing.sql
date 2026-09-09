-- Voyage Outdoor · 0003 Smart Pack
--
-- EVERY ROW HERE RECORDS WHICH RULESET PRODUCED IT.
--
-- These tables hold the output of deterministic engines, and the whole value of
-- a deterministic engine is that its answer can be explained and reproduced.
-- An unstamped row says "you need a headlamp" with no way to find out which
-- rule said so or whether that rule still exists. So `ruleset_version` is not
-- optional metadata — it is what separates a decision from an assertion.
--
-- Nothing in this migration is written by a model. The AI layer in Phase 4
-- reads these rows and writes prose about them into ai_outputs, which is a
-- different table for the reason stated in 0001.

-- ============ the pack ============

create table public.packing_lists (
  id uuid primary key default gen_random_uuid(),
  adventure_id uuid not null references public.adventures(id) on delete cascade,

  generated_at timestamptz not null default now(),
  ruleset_version text not null,

  -- Inputs hash, rule counts, which weather rows were in scope, how many items
  -- each classification produced. Enough to answer "why did it say that" for a
  -- list generated three months ago against a forecast that has since changed.
  generation_snapshot jsonb not null default '{}',

  -- ONE LIST PER ADVENTURE. Regenerating replaces it rather than adding a
  -- second, because two lists for one race is a question about which is real,
  -- and the answer would be decided by whichever query ran first. VoyageOS
  -- keeps a history of packing_lists and pays for it with exactly that
  -- ambiguity — its readers all order by generated_at and hope.
  unique (adventure_id)
);

create table public.packing_list_items (
  id uuid primary key default gen_random_uuid(),
  list_id uuid not null references public.packing_lists(id) on delete cascade,

  -- The gear this line resolved to, when the locker had something. NULL is the
  -- MISSING case and is the whole point of the classification below: a pack
  -- list that only lists what you own cannot tell you what you lack.
  gear_item_id uuid references public.gear_items(id) on delete set null,

  name text not null,
  category_key text references public.gear_categories(key) on delete set null,
  qty int not null default 1 check (qty > 0),

  -- WHAT THE ENGINE DECIDED. A closed set the code branches on (§8).
  classification text not null
    check (classification in ('required','recommended','optional','not_needed','missing')),

  -- WHAT THE PERSON HAS DONE ABOUT IT (§9). Deliberately separate from the
  -- classification: one is the engine's opinion and the other is the state of
  -- a physical object in a bag, and conflating them is how a list stops being
  -- able to say "you were told to bring this and you have not".
  state text not null default 'not_selected'
    check (state in ('not_selected','selected','packed','verified',
                     'in_use','returned','missing','damaged')),

  -- Visually distinct, and the readiness check counts it separately. Set by
  -- the engine for anything a race mandates or safety depends on.
  critical boolean not null default false,

  -- PROVENANCE. rule_key names the rule that produced this line; reason is its
  -- structured output rendered as one sentence. Both come from code — the AI
  -- layer may rewrite `reason` into ai_outputs later, never into this column.
  rule_key text,
  reason text,
  source text not null default 'rule'
    check (source in ('rule','mandatory','manual')),

  sort int not null default 0,
  created_at timestamptz not null default now()
);
create index on public.packing_list_items (list_id, classification);
create index on public.packing_list_items (gear_item_id);

-- ============ warnings ============
--
-- Kept out of packing_list_items because a warning is not a thing you pack.
-- "Your shoes have 620 km on them" and "bring a headlamp" are different kinds
-- of statement, and putting them in one table would mean every reader has to
-- filter one out of the other.

create table public.pack_warnings (
  id uuid primary key default gen_random_uuid(),
  list_id uuid not null references public.packing_lists(id) on delete cascade,
  gear_item_id uuid references public.gear_items(id) on delete set null,

  key text not null,                    -- shoe_worn · headlamp_burn_short · …
  severity text not null default 'note'
    check (severity in ('note','caution','critical')),
  message text not null,
  rule_key text not null,
  detail jsonb not null default '{}',   -- the numbers the rule compared
  created_at timestamptz not null default now()
);
create index on public.pack_warnings (list_id);

-- ============ engine output, kept ============
--
-- Compatibility and gear-health results are stored rather than recomputed on
-- every read: the locker list shows a condition figure per row, and running
-- the engine per row per render is how a list of forty items becomes slow.
--
-- Stored WITH the ruleset version that produced it, so a stale row is
-- recognisable as stale rather than silently trusted after the thresholds
-- change.

create table public.rule_evaluations (
  id uuid primary key default gen_random_uuid(),
  adventure_id uuid references public.adventures(id) on delete cascade,
  gear_item_id uuid references public.gear_items(id) on delete cascade,

  rule_key text not null,
  ruleset_version text not null,
  state text not null
    check (state in ('compatible','possibly_compatible','not_recommended','unknown')),
  -- The facts the rule compared, so the answer can be re-derived by hand.
  -- UNKNOWN carries what was MISSING, which is the actionable part: "no burn
  -- time recorded for this headlamp" tells the owner what to fill in.
  detail jsonb not null default '{}',
  evaluated_at timestamptz not null default now(),

  unique (adventure_id, gear_item_id, rule_key)
);
create index on public.rule_evaluations (gear_item_id);

-- Gear health is per item and independent of any adventure, so it lives on the
-- item rather than in rule_evaluations. condition_pct already exists on
-- gear_items from 0001; these record how it was arrived at.
alter table public.gear_items
  add column if not exists health_ruleset text,
  add column if not exists health_detail jsonb not null default '{}',
  add column if not exists health_evaluated_at timestamptz;

-- ============ RLS ============
--
-- Same doctrine as 0001: the API seam on the service key is the enforcement
-- point, and these are a correct second line rather than a stale one.

alter table public.packing_lists      enable row level security;
alter table public.packing_list_items enable row level security;
alter table public.pack_warnings      enable row level security;
alter table public.rule_evaluations   enable row level security;

create policy "lists via adventure" on public.packing_lists for all
  using (exists (select 1 from public.adventures a
                 where a.id = adventure_id and a.user_id = auth.uid()))
  with check (exists (select 1 from public.adventures a
                      where a.id = adventure_id and a.user_id = auth.uid()));

create policy "list items via list" on public.packing_list_items for all
  using (exists (select 1 from public.packing_lists l
                 join public.adventures a on a.id = l.adventure_id
                 where l.id = list_id and a.user_id = auth.uid()))
  with check (exists (select 1 from public.packing_lists l
                      join public.adventures a on a.id = l.adventure_id
                      where l.id = list_id and a.user_id = auth.uid()));

create policy "warnings via list" on public.pack_warnings for all
  using (exists (select 1 from public.packing_lists l
                 join public.adventures a on a.id = l.adventure_id
                 where l.id = list_id and a.user_id = auth.uid()))
  with check (exists (select 1 from public.packing_lists l
                      join public.adventures a on a.id = l.adventure_id
                      where l.id = list_id and a.user_id = auth.uid()));

create policy "evaluations via gear" on public.rule_evaluations for all
  using (exists (select 1 from public.gear_items g
                 where g.id = gear_item_id and g.user_id = auth.uid()))
  with check (exists (select 1 from public.gear_items g
                      where g.id = gear_item_id and g.user_id = auth.uid()));
