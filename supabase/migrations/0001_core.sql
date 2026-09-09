-- Voyage Outdoor · 0001 core schema
--
-- Conventions, and the reasons they are these conventions:
--
--   uuid PKs via gen_random_uuid()  — native since PG13; no uuid-ossp extension
--                                     to remember to install.
--   timestamptz everywhere          — an adventure crosses timezones by design.
--   date for calendar days          — a race is on a day, not at an instant.
--   jsonb for activity attributes   — see THE ATTRIBUTE MODEL below.
--
-- CHECK CONSTRAINTS ARE FOR STATE MACHINES, NOT TAXONOMIES.
--
-- VoyageOS's items.category is a CHECK enumerating ten travel categories. Every
-- piece of outdoor equipment it has ever stored collapsed into the single value
-- 'activity_gear', and widening it means a migration. So: `status` gets a CHECK
-- (it is a closed set of states the code branches on), `category_key` does not
-- (it is a taxonomy that grows). Categories are rows in gear_categories.

create extension if not exists pgcrypto;

-- ============ identity ============

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  name text,
  unit_system text not null default 'metric'
    check (unit_system in ('metric','imperial')),
  locale text not null default 'en',
  created_at timestamptz not null default now()
);

create table public.user_preferences (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  -- Distance is the unit that matters here — shoe mileage, race length — and it
  -- is not always implied by unit_system: metric runners routinely think in km
  -- while weighing a vest in grams, which is the default pair below.
  distance_unit text not null default 'km' check (distance_unit in ('km','mi')),
  weight_unit   text not null default 'g'  check (weight_unit in ('g','oz')),
  notification_daily_cap int not null default 3
    check (notification_daily_cap between 1 and 5),
  quiet_hours jsonb not null default '{"start":"22:00","end":"07:00"}',
  extras jsonb not null default '{}',
  created_at timestamptz not null default now()
);

-- ============ the activity system ============
--
-- THE ATTRIBUTE MODEL (Master Prompt §4).
--
-- Every activity needs fields no other activity has: a trail shoe has stack
-- height and lug depth, a fly rod has line weight and action. Three ways to
-- model that, and only one of them is right at this scale:
--
--   a column per field   — unbounded width, a migration per activity
--   a full EAV table     — every read becomes a pivot; unqueryable by hand
--   jsonb per row        — one column, GIN-indexable, readable in the console
--
-- The shape of each activity's jsonb lives in activities.attribute_schema and
-- is enforced in pydantic at the API boundary — NOT by a database constraint. A
-- constraint here would have to be rewritten to add an activity, which is the
-- exact rework this model exists to avoid.
--
-- Four activities are seeded. ONE is built (trail_running). The other three
-- exist so the schema is exercised by more than a single consumer before the
-- architecture is called general — a schema proven by one activity is not
-- proven. See api/tests/test_activity_schemas.py.

create table public.activities (
  key text primary key,
  name text not null,
  -- {version, gear: {category_key: {field: spec}}, adventure: {field: spec}}
  attribute_schema jsonb not null default '{}',
  -- Built and reachable in the app, vs. defined in schema only. V1 ships with
  -- exactly one true row; the rest are false and have no UI.
  built boolean not null default false,
  sort int not null default 0,
  created_at timestamptz not null default now()
);

create table public.gear_categories (
  key text primary key,
  name text not null,
  -- null = applies to every activity (a headlamp is a headlamp)
  activity_key text references public.activities(key) on delete cascade,
  parent_key text references public.gear_categories(key) on delete set null,
  sort int not null default 0
);
create index on public.gear_categories (activity_key);

-- ============ products (thin in V1 — Master Prompt §0.4) ============
--
-- No live product database in V1: admin/manual rows only. The tables exist now
-- because gear_items references them optionally, and adding a FK later is a
-- migration that must follow a deploy rather than lead one.
--
-- products.specs IS OBJECTIVE FACT. Generated text lives in ai_outputs and the
-- two never merge — that is §28 ("never let AI silently overwrite factual
-- specs") enforced by the schema instead of by care.

create table public.products (
  id uuid primary key default gen_random_uuid(),
  brand text not null,
  model text not null,
  category_key text references public.gear_categories(key) on delete set null,
  activity_key text references public.activities(key) on delete set null,
  generation text,
  specs jsonb not null default '{}',
  source text not null default 'manual'
    check (source in ('manual','curated','import')),
  created_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now()
);
create index on public.products (activity_key, category_key);

create table public.product_variants (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references public.products(id) on delete cascade,
  label text,
  size text,
  colorway text,
  weight_g int,
  attributes jsonb not null default '{}'
);
create index on public.product_variants (product_id);

-- ============ the Gear Locker (§5) ============

create table public.gear_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,

  -- Both optional, and usually null in V1. A locker entry is a thing the person
  -- OWNS; a product is a thing that EXISTS. Keeping them separate is what lets
  -- manual entry be a first-class path rather than a degraded one (§6).
  product_id uuid references public.products(id) on delete set null,
  variant_id uuid references public.product_variants(id) on delete set null,

  name text not null,
  brand text,
  model text,
  category_key text references public.gear_categories(key) on delete set null,
  activity_key text references public.activities(key) on delete set null,

  size text,
  color text,
  weight_g int check (weight_g is null or weight_g >= 0),
  purchase_date date,
  purchase_price_cents int check (purchase_price_cents is null or purchase_price_cents >= 0),
  currency text,
  photo_key text,                       -- private bucket object; signed URLs only
  serial_number text,
  notes text,

  -- DERIVED, NOT TYPED. Gear health (§12) computes this from usage against the
  -- category's thresholds. It is stored so a list query does not have to run the
  -- engine per row, and it is recomputed — never hand-edited — so it cannot
  -- drift from the usage that justifies it.
  condition_pct int check (condition_pct is null or condition_pct between 0 and 100),

  -- A closed set the code branches on, so a CHECK is right here.
  status text not null default 'active'
    check (status in ('active','retired','lost','damaged')),
  favorite boolean not null default false,

  attributes jsonb not null default '{}',   -- validated against activities.attribute_schema
  tags text[] not null default '{}',

  retired_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on public.gear_items (user_id, status);
create index on public.gear_items (user_id, activity_key, category_key);
create index on public.gear_items using gin (attributes);
create index on public.gear_items using gin (tags);

-- ============ adventures (§7) ============
--
-- FULLY SEPARATE FROM VoyageOS's TRIP (§0.7). Different project, different
-- database — but stated here too, because the pressure to make this "just a
-- trip with a distance" arrives during implementation, not during design.
--
-- The table lands in 0001 rather than in the Phase 2 migration so the FK graph
-- is whole from the start: gear_usage.adventure_id points here, and adding that
-- FK later is a migration that must follow a deploy instead of leading one.
-- Phase 2 builds the API and the screens, not the table.

create table public.locations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  country_code text,
  lat double precision,
  lng double precision,
  elevation_m int,
  source text not null default 'manual',
  created_at timestamptz not null default now()
);

create table public.adventures (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  activity_key text not null references public.activities(key),
  subtype text,
  title text not null,

  location_id uuid references public.locations(id) on delete set null,
  place_name text,
  country_code text,
  lat double precision,
  lng double precision,

  start_date date not null,
  end_date date not null,
  status text not null default 'draft'
    check (status in ('draft','planned','active','completed','archived')),

  -- distance_km · elevation_gain_m · elevation_loss_m · expected_hours ·
  -- terrain · technicality · aid_stations · night_hours · mandatory_kit[]
  attributes jsonb not null default '{}',

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (end_date >= start_date)
);
create index on public.adventures (user_id, status, start_date);
create index on public.adventures using gin (attributes);

create table public.weather_snapshots (
  id uuid primary key default gen_random_uuid(),
  adventure_id uuid not null references public.adventures(id) on delete cascade,
  forecast_date date not null,
  temp_min double precision,
  temp_max double precision,
  precip_prob double precision,
  wind_kph double precision,
  uv double precision,
  provider text not null,
  fetched_at timestamptz not null default now(),
  unique (adventure_id, forecast_date, provider)
);

-- ============ usage & maintenance (§5, §12) ============

create table public.gear_usage (
  id uuid primary key default gen_random_uuid(),
  gear_item_id uuid not null references public.gear_items(id) on delete cascade,
  -- Null is ordinary: a training run is usage without an adventure.
  adventure_id uuid references public.adventures(id) on delete set null,
  occurred_on date not null,
  distance_m int check (distance_m is null or distance_m >= 0),
  duration_s int check (duration_s is null or duration_s >= 0),
  conditions jsonb not null default '{}',   -- terrain, wet, temp, night
  notes text,
  created_at timestamptz not null default now()
);
create index on public.gear_usage (gear_item_id, occurred_on desc);

create table public.maintenance_events (
  id uuid primary key default gen_random_uuid(),
  gear_item_id uuid not null references public.gear_items(id) on delete cascade,
  kind text not null,                       -- wash · reproof · resole · service · inspect
  occurred_on date not null,
  notes text,
  cost_cents int check (cost_cents is null or cost_cents >= 0),
  next_due_on date,
  created_at timestamptz not null default now()
);
create index on public.maintenance_events (gear_item_id, occurred_on desc);

-- ============ ops ============
--
-- ai_runs exists from the first commit even though nothing calls a model until
-- Phase 4. Cost observability added later is cost observability for the period
-- after you started worrying — and the number that matters (what a Smart Pack
-- over a full locker actually costs) can only be measured against a baseline.

create table public.ai_runs (
  id bigint generated always as identity primary key,
  user_id uuid,
  task text not null,
  provider text,
  model text,
  tokens_in int,
  tokens_out int,
  cost_usd numeric(10,5),
  latency_ms int,
  stop_reason text,
  created_at timestamptz not null default now()
);
create index on public.ai_runs (user_id, created_at desc);

-- Generated text, kept apart from the facts it describes (§28).
create table public.ai_outputs (
  id uuid primary key default gen_random_uuid(),
  subject_type text not null,               -- gear_item · adventure · packing_list · product
  subject_id uuid not null,
  task text not null,
  payload jsonb not null default '{}',
  model text,
  prompt_version text,
  created_at timestamptz not null default now(),
  unique (subject_type, subject_id, task)
);

-- ============ RLS ============
--
-- WRITTEN CORRECTLY ON DAY ONE, unlike the policies this project's parent
-- shipped. VoyageOS's 0001 policies are owner-only and were left behind when
-- trips became shareable; they are load-bearing again the moment any
-- client-direct database access exists, and they are wrong for that world.
--
-- The enforcement point here is still the API seam — FastAPI holds the service
-- key, which bypasses RLS, and the app's anon key reaches /auth/v1 and nothing
-- else. These policies are the second line. The difference is that this second
-- line is correct, so adding a realtime subscription or an edge function later
-- is a feature rather than a security review.

alter table public.profiles          enable row level security;
alter table public.user_preferences  enable row level security;
alter table public.activities        enable row level security;
alter table public.gear_categories   enable row level security;
alter table public.products          enable row level security;
alter table public.product_variants  enable row level security;
alter table public.gear_items        enable row level security;
alter table public.gear_usage        enable row level security;
alter table public.maintenance_events enable row level security;
alter table public.locations         enable row level security;
alter table public.adventures        enable row level security;
alter table public.weather_snapshots enable row level security;
alter table public.ai_outputs        enable row level security;
alter table public.ai_runs           enable row level security;

-- own rows
create policy "own profile" on public.profiles
  for all using (id = auth.uid()) with check (id = auth.uid());
create policy "own prefs" on public.user_preferences
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "own gear" on public.gear_items
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "own adventures" on public.adventures
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- child rows, reachable through the parent the caller owns
create policy "usage via gear" on public.gear_usage for all
  using (exists (select 1 from public.gear_items g
                 where g.id = gear_item_id and g.user_id = auth.uid()))
  with check (exists (select 1 from public.gear_items g
                      where g.id = gear_item_id and g.user_id = auth.uid()));
create policy "maintenance via gear" on public.maintenance_events for all
  using (exists (select 1 from public.gear_items g
                 where g.id = gear_item_id and g.user_id = auth.uid()))
  with check (exists (select 1 from public.gear_items g
                      where g.id = gear_item_id and g.user_id = auth.uid()));
create policy "weather via adventure" on public.weather_snapshots for all
  using (exists (select 1 from public.adventures a
                 where a.id = adventure_id and a.user_id = auth.uid()))
  with check (exists (select 1 from public.adventures a
                      where a.id = adventure_id and a.user_id = auth.uid()));

-- reference data: readable by any signed-in user, writable by nobody through
-- the anon key. The API's service key seeds and maintains these.
create policy "read activities" on public.activities
  for select using (auth.role() = 'authenticated');
create policy "read categories" on public.gear_categories
  for select using (auth.role() = 'authenticated');
create policy "read products" on public.products
  for select using (auth.role() = 'authenticated');
create policy "read variants" on public.product_variants
  for select using (auth.role() = 'authenticated');
create policy "read locations" on public.locations
  for select using (auth.role() = 'authenticated');

-- ai_outputs is readable when you can reach its subject; the API writes it.
-- No blanket policy: a subject_type/subject_id pair cannot be joined
-- generically, so each read path checks its own parent. Deliberately no SELECT
-- policy here means the anon key sees nothing, which is the safe default until
-- a client-direct read path actually exists.

-- ai_runs is ops data about a user, not data FOR them. RLS on, no policy: the
-- service key reads it, nobody else does.
