# Voyage Outdoor — Phase 0 Audit

Against `Voyage_Outdoor_Master_Prompt_v2.md` §30. Nothing has been built. This
document is the deliverable; approval is the gate to Phase 1.

Audited: `/Users/macbook/Desktop/voyageos` @ `0aec8fa` (main, 8 commits ahead of
origin). No VoyageOS file was modified.

---

## 1. Existing architecture

### Stack

| Layer | What it actually is |
|---|---|
| App | Expo SDK `~54.0.35`, React Native `0.81.5`, React `19.1.0`, TS `5.9`. **React Navigation v7** (native-stack + bottom-tabs) — *not* expo-router. Prebuilt iOS project in `app/ios/`. EAS build + submit, `com.ealghunaim.voyageos`, shipped v1.1.0 (build 12), ASC app id 6796236314. |
| API | FastAPI monolith, `api/main.py` includes **24 routers**. supabase-py on the **service key**. APScheduler **in-process**: notification governor (60s), weather (6h). Reports `version 0.6.0`. |
| DB | Supabase Postgres. **39 plain-SQL migrations** in `supabase/migrations/`. uuid PKs, timestamptz, jsonb for variable payloads. |
| Tests | 45 pytest files in `api/tests/`, plus 11 standalone TS "check" scripts in `app/scripts/` (`deeplink_check.ts`, `paywall_check.ts`, …) run as invariant proofs. |

App source is small and flat: `App.tsx` (538 lines, holds the whole navigator +
auth gate), `src/screens/` (20 files), `src/components/` (24), and ~30 loose
modules in `src/`. **No state library, no react-query, no persisted cache.**

### Auth and the access seam

- **Client** (`app/src/auth.ts`, 233 lines): Supabase Auth over **raw REST**, no
  `supabase-js`. Tokens in `expo-secure-store`. Refresh, recovery-link adoption,
  password re-verification for destructive actions, sign-out hook registry.
- **Server** (`api/core/auth.py`): verifies the bearer token by calling
  `{supabase}/auth/v1/user`, 300s TTL cache, auto-provisions the `profiles` row
  on first sight.
- **A second, coarser gate**: `shared_secret_guard` middleware in `main.py`
  requires `x-voyageos-key` on every path except `/health`, `/docs`,
  `/openapi.json` and the RevenueCat webhook. It accepts the **current or
  previous** key so a rotation can overlap a store release.
- **RLS exists but is explicitly not authoritative.** The closing comment of
  `0001_v05_core.sql` states it outright: every data path goes through FastAPI
  on the service key, which bypasses RLS; the client's anon key reaches
  `/auth/v1` and nothing else. Access is decided in `api/core/trips.py` —
  `membership()` → `role_for()` → `owned_trip(writing, scope)`, with scopes
  `PLAN` / `RECORD` / `PERSONAL` / `LIFECYCLE` and roles `owner` / `editor` /
  `viewer`. Both "no such trip" and "not your trip" answer 404, deliberately, so
  the endpoint is not an id oracle.

### The AI layer — `api/ai_gateway/gateway.py`

The single choke point for every model call. 204 lines, and the most directly
reusable file in the repository.

- `TASK_ROUTE`: task → tier (`small` / `mid` / `frontier`) → `settings.model_small
  / model_mid / model_frontier` = `claude-haiku-4-5` / `claude-sonnet-5` /
  `claude-opus-5`. **Switching a task's model tier is a one-line edit to a dict.**
- `TASK_MAX_TOKENS`: per-task output ceiling, sized at ~2× observed peak, with
  the measured numbers in the comments. Exists because a blanket default hid a
  50% truncation failure rate in `packing_generate`.
- `TIER_PRICES`: USD per Mtok per tier, dated and sourced.
- `check_budget()`: per-user daily USD cap (`ai_daily_cost_cap_usd`, default
  **$0.50**), 429 when exhausted.
- Every call logs to `ai_runs` (tokens in/out, cost, latency, stop_reason). The
  insert is wrapped so observability can never take the feature down.
- **Prompt caching**: system prompts ≥ 4000 chars are marked `ephemeral`.
- One transient retry. `stop_reason == "max_tokens"` is surfaced as
  `AiResult.truncated` so callers can tell a *length* failure from a *format*
  one — they need different retry prompts.

### The guide "phase engine" (§0.6, §1.2) — with one correction

The master prompt describes "fast first-pass on a cheap tier, parallel second
pass on a stronger tier". That is the effect. The mechanism differs in a way
that matters for how it gets reused:

- **The parallelism is client-side.** `GET /v1/trips/{id}/guide/part/{a|b}` are
  two independent endpoints. `Guide.tsx:130` fires both with `fetch`, merges
  each as it lands (A and B write disjoint fields), resolves the loading state
  on A, and **swallows a B failure** so a phase-B hiccup can't block the guide.
- **Tiering is per phase**: `guide_a` → `small` (Know + Eat, fast paint),
  `guide_b` → `mid` (Play + Visit + Go, richer). Per-phase token ceilings too
  (`_PART_MAX_TOKENS = {"a": 3000, "b": 8000}`) — B was being cut off mid-JSON
  under a shared 3000.
- **Caching** is a row per `(trip_id, destination_id, phase)` in
  `trip_guide_parts`, upserted, cached forever unless `regenerate=true`, stamped
  `model·GUIDE_PROMPT_VERSION`.
- **Every phase has a `sanitize_*` whitelist gate.** Unknown keys are dropped,
  strings clipped, enums constrained, numbers clamped. Model output never
  reaches the database in the shape the model produced it.
- **Post-response background work**: geocoding runs in `BackgroundTasks` after
  the response, is idempotent (re-reads the payload rather than taking it as an
  argument), swallows every failure, and resumes on the next read.

### The deterministic engines that already exist

§0.5 proposes "deterministic code, not model calls" as a new rule. It is already
the house style, and the existing implementations are better than a fresh start:

- **`api/packing/quantity_engine.py`** — *"Law 2: the model proposes quantities;
  THIS module's number wins."* Pure functions, no I/O, `ItemClass` enum, hard
  caps, style multipliers, documented ordering (laundry → base rate → style
  multiplier → cap), exhaustively tested. Divergence from the model's proposal
  is **counted and stored** in `generation_snapshot` for evals.
- **`api/weather/rules.py`** — `RULESET = "wx-v1"`, thresholds as named module
  constants, pure `evaluate(days, place) -> insights[]`. Each insight carries
  `key`, `severity`, `reason`, and `items[]` with **dedupe terms** so "Sunscreen"
  never duplicates an existing "Sunscreen SPF 50". Docstring: *"No model in the
  decision path; a model may only ever rephrase these outputs."*
- **`api/packing/service.py`** — the whole pipeline: `build_context` →
  `context_hash` → cache-hit check → gateway → pydantic validate → **retry once
  with a different prompt depending on truncation vs. validation failure** →
  quantity engine overrides → catalog link → persist with full
  `generation_snapshot` → honest template fallback on double failure.

### Ask-AI precedent

`api/qa/router.py` is 59 lines: assemble trip + weather + packing + guide
context, `small` tier, 120-word ceiling, and hard refusal rules baked into the
system prompt ("NEVER state visa, vaccination, customs, or airline
regulations"). That is the shape Ask Outdoor AI wants, plus §16's priority
ordering.

### Weather

`api/weather/provider.py` — **Open-Meteo primary (free, no API key)**, MET Norway
fallback (needs an identifying User-Agent per their ToS; no rain probability, so
the rain rule stays honestly silent on fallback data), AccuWeather optional
behind a key, archive endpoint for historicals, geocoding via Open-Meteo's
geocoding API. Snapshots land in `weather_snapshots`, refreshed by the 6h job,
15-day horizon. **Voyage Outdoor needs no new weather vendor.**

### Design system

`app/src/theme.ts` (184 lines) is the whole system, and says so:

- `F` — Satoshi reg/med/bold, defaulted app-wide by patching `Text`/`TextInput`
  `defaultProps` in `App.tsx` (an audit found 71 Texts and 14 TextInputs missing
  the font).
- `P` — colour tokens. Ramp: ink `#0D182A` → indigo `#1B2CFB` → blue `#3465FF`
  → cyan `#00C2FF` → sky `#6EE7FF`. Includes `warningInk` (`#B45309`) split out
  from `warning` because the fill amber is 2.1:1 on white and unreadable as type.
- `S` — 4pt grid. `RA` — radii. `E` — three deliberate elevation steps.
  `T` — 7 type styles. `FOLD` — the V motif, depth 18 (used once, in `TripHub`).
- Plus destination-accent machinery: `FLAG_ACCENT` (56 country codes),
  `accentFor` hash palette, and `tint` / `luminance` / `onColor` / `lift`
  helpers — `lift` exists because a navy flag accent merges with the ink contour
  in filled icons.
- `ui.tsx`: `Btn`, `Card`, `Chip`, `Field`, `Progress`, `EyeIcon`.

### Notifications and monetization

- `expo-notifications` + `device_tokens`; `api/notifications/{governor,push,worker}.py`
  implement a per-user daily cap, quiet hours, topic dedupe and `idem_key` on the
  schedule row.
- RevenueCat (`react-native-purchases`), tier ladder in
  `api/subscriptions/tiers.py` (**count-based**: free 1 / explorer 3 / traveler 6
  / voyager 12 trips), webhook verified by HMAC-SHA256 **and** a static
  Authorization header, `402` carrying a structured `LimitInfo` body that the
  client turns into a typed `PaywallError`.

---

## 2. What Voyage Outdoor should reuse

**Copy, don't share.** Separate projects (§0.2) means these are forks, not imports.

| Reuse near-verbatim | Why |
|---|---|
| `api/ai_gateway/gateway.py` | Change `TASK_ROUTE` keys and ceilings; everything else applies unchanged. |
| `api/weather/{provider,service,rules,job}.py` | Providers and the snapshot job are activity-agnostic. Retune `rules.py` thresholds for trail running. |
| `api/core/{config,db,auth}.py` + `main.py` middleware | The fresh-client-per-call rule in `db.py` is a fix for a real class of cloud 500s (errno-11). Don't re-derive it. |
| `api/notifications/*` | Governor, quiet hours, dedupe, idempotency — all §21 wants. |
| `api/subscriptions/*` | Same RevenueCat machinery, new products. |
| `app/src/api.ts` `req()` | Typed errors, 401 refresh-and-retry, `readBody` for 204s (a real shipped crash). |
| `app/src/auth.ts` | 233 lines of GoTrue-over-REST against a *different* project. |
| `app/src/theme.ts` token layer (`F/S/RA/E/T` + `P`) | Keep the scales, replace the palette semantics. |
| `app/src/components/ui.tsx`, `TopBar`, `ModalScreen`, `JourneyLoader` | Generic. |
| `app/scripts/*_check.ts` convention | Cheap invariant proofs outside pytest. |
| Migration conventions + the `0001` doc style | The documented-decision style is why this audit was possible at all. |

| Reuse the *pattern*, write new code | |
|---|---|
| `packing/quantity_engine.py` | The template for gear-health and compatibility engines: pure, versioned, enum-typed, tested, divergence-logged. |
| `packing/service.py` pipeline | context → hash → cache → gateway → validate → **engine overrides model** → persist snapshot → fallback. |
| `guide/service.py` `sanitize_*` | Whitelist gate on every model payload. Non-negotiable. |
| `qa/router.py` | Ask Outdoor AI's shape. |
| `core/trips.py` | Becomes `core/adventures.py`, same scope/role seam even though V1 is single-player. |

**Do not copy:**

- `trips` / `destinations` / `activities` and everything keyed to them (§0.7).
- `items` / `gear_profiles` / `gear_profile_items`. Superficially a gear locker;
  actually a *packing-template* model — `items.category` is a **CHECK constraint
  enumerating ten travel categories**, all outdoor equipment collapses into
  `activity_gear`, and there is no size, weight, condition, usage or maintenance.
  Wrong shape, and the CHECK constraint is a lesson: don't enumerate categories
  in SQL.
- `airports.ts` (3,417 lines), `airlines.ts`, `flights/`, `flights/routes.py`.
- The document crypto vault, invites/sharing, `photos/wikimedia.py`, `phrases`,
  `family_play`, journal, debrief.
- `FLAG_ACCENT` and the whole "one accent per destination" idea. It is travel
  identity. Voyage Outdoor's accent should be fixed or activity-derived.

---

## 3. The §0 decisions, now that the code is visible

**§0.1 — V1 = Trail Running only.** Confirmed. Nothing in the codebase argues
against it. One inherited lesson to apply: use a `gear_categories` table or a
plain text column validated at the API boundary — **never a CHECK constraint**
enumerating categories, which is exactly what boxed VoyageOS's `items` table in.

**§0.2 — Separate Supabase project + Render service.** Confirmed, strongly, and
for a reason the prompt doesn't state: RLS is not authoritative in VoyageOS and
access is decided in `api/core/trips.py`. Sharing a database would mean two API
seams enforcing two different membership models over one set of tables, with RLS
underneath too stale to catch a mistake. Separation is the only defensible call.

Two amendments:

- **The cold-start premise is unverified in this repo.** There is no
  `render.yaml`, no `Procfile`, and no mention of a diagnosed free-tier
  cold-start problem in `BUILD.md`, `README.md` or `DEPLOY-TONIGHT.md`. The
  *decision* (pay for Starter from day one) is still right for a stronger
  reason: an in-process APScheduler that must tick every 60s is fundamentally
  incompatible with a service that spins down when idle. I'm confirming the
  decision and flagging the stated justification as not found in the code.
- **The in-process scheduler is an inherited constraint, not a free pattern.**
  VoyageOS runs both background jobs inside the web process. Copy that and
  Voyage Outdoor cannot run a second web instance without duplicate job runs —
  `max_instances=1` is per-process, not per-service. Decide this in Phase 1,
  not in Phase 6.

**§0.3 — Separate auth at launch.** Confirmed. Duplicating `auth.ts` against a
second Supabase project is a copy, not an integration. Worth naming the future
cost honestly: Phase 7 SSO is not "a link-my-account button" — it needs a shared
IdP or a token-exchange service. That's a reason to defer it, not a reason it's
easy later.

**§0.4 — No live product DB in V1.** Confirmed, and the pattern already exists:
`api/gear/router.py::_resolve_item` matches a global catalog row by name and
otherwise creates a user-owned one — *"the catalog grows from use"*. That is
precisely the right V1 posture and it's already written.

**§0.5 — Deterministic vs AI.** Confirmed; it's already house style. One
addition from what VoyageOS learned: the boundary is enforced **structurally**,
not just by intent. `sanitize()` means model output cannot introduce fields, and
`_apply_quantity_engine` overwrites the model's number after the fact. Carry
both over — every engine output should be a typed structure the AI *narrates*,
never free text the AI *produces*.

**§0.6 — Reuse the phase-engine pattern.** Confirmed with a correction that
changes the design. The parallelism is client-side across two independent
endpoints, and it works *because Know+Eat and Play+Visit+Go are genuinely
independent*. Smart Pack's phases are not: the REQUIRED classification is what
MISSING is computed against. So:

- Reuse `gateway.py`, the per-task tiering, the caching-by-key and the
  sanitize gate **wholesale**.
- Smart Pack should be **one deterministic pass, then one narrative call** — not
  two parallel model calls.
- The parallel-phase *fetch* pattern still applies where halves are independent:
  e.g. the pack narrative and a gear-health sweep can load side by side.

**§0.7 — ADVENTURE separate from TRIP.** Confirmed, and a separate project makes
it structural rather than a matter of discipline.

### A decision §0 does not make, and needs to

VoyageOS has **no dark mode** (`app.json: userInterfaceStyle: "light"`,
`NavigationContainer dark:false`, and `P` carries only light tokens) and **no
offline layer** (no AsyncStorage, no persisted query cache — every screen fetches
on mount; `expo-secure-store` holds only the session and the biometric flag).

§19 demands "excellent dark mode" and §20 demands offline-first. **There is
nothing to inherit for either.** Both are cheap to build in from commit one and
expensive to retrofit in Phase 6 — a light-only token set means every screen
written before the dark pass gets revisited. Recommendation: `P` becomes a
light/dark token pair on day one, and a persisted cache sits under the API
client on day one.

---

## 4. Proposed spin-off architecture

```
voyage-outdoor/                     ← new repo, new remote
  app/                              Expo 54 · RN 0.81 · React Navigation v7
  api/                              FastAPI
    core/       config · db · auth · adventures (the access seam)
    ai_gateway/ gateway.py (forked) · prompts.py
    activities/ registry + trail_running schema
    gear/       locker CRUD · usage · maintenance
    adventures/ CRUD · trail-running form
    packing/    rules engine (deterministic) · service · narrative
    engines/    compatibility.py · gear_health.py · gear_match.py   ← pure, versioned
    weather/    forked
    products/   thin: manual + curated seed
    ai/         ask.py (Ask Outdoor AI)
    notifications/ forked
    subscriptions/ forked
  supabase/migrations/              new project, new numbering from 0001
```

Separate Supabase project, separate Render **Starter** service, separate
RevenueCat app, separate EAS project and bundle id. Shared with VoyageOS: the
Anthropic account, and nothing else.

### Database schema (JSONB attribute model, §4)

Identity, mirroring VoyageOS:

```
profiles(id → auth.users, email, name, unit_system, locale, created_at)
user_preferences(user_id PK, units, notification prefs, extras jsonb)
```

Activity system — the part that must not need rework for Phase 7:

```
activities(id, key unique, name, attribute_schema jsonb, active)
    seeded: trail_running (built) · hiking · fishing · fly_fishing (schema only)
gear_categories(id, key, name, activity_key nullable, parent_id, sort)
```

`attribute_schema` describes the activity-specific fields for both gear and
adventures. Validation happens **at the API boundary in pydantic**, not in a DB
constraint — that is the lesson from `items.category`.

Gear:

```
gear_items(id, user_id, product_id?, variant_id?,
           name, brand, model, category_id, activity_key,
           size, color, weight_g, purchase_date, purchase_price_cents, currency,
           photo_key, serial_number, notes,
           condition_pct, status(active|retired|lost|damaged), favorite,
           attributes jsonb,        -- size/stack/drop/outsole/lug/terrain/waterproof/mileage
           tags text[], created_at)
gear_usage(id, gear_item_id, adventure_id?, occurred_on,
           distance_m, duration_s, conditions jsonb, notes)
maintenance_events(id, gear_item_id, kind, occurred_on, notes, cost_cents, next_due_at)
```

Adventures:

```
adventures(id, user_id, activity_key, subtype, title,
           location_id?, place_name, country_code, lat, lng,
           start_date, end_date, status(draft|planned|active|completed|archived),
           attributes jsonb,        -- distance_km, elevation_gain_m, expected_hours,
                                    -- terrain, technicality, aid_stations, night_hours,
                                    -- mandatory_kit[]
           created_at)
locations(id, name, country_code, lat, lng, elevation_m, source)
weather_snapshots(id, adventure_id, forecast_date, temp_min, temp_max,
                  precip_prob, wind_kph, uv, provider, fetched_at)
```

Packing:

```
packing_lists(id, adventure_id, generated_at, ruleset_version,
              generation_snapshot jsonb)
packing_list_items(id, list_id, gear_item_id?, product_id?,
                   name, category_id, qty,
                   classification(required|recommended|optional|not_needed|missing),
                   state(not_selected|selected|packed|verified|in_use|returned|missing|damaged),
                   critical bool,
                   source(rule|ai|manual|template), rule_key, reason, sort)
pack_warnings(id, list_id, key, severity, message, rule_key, gear_item_id?)
```

Engine outputs (deterministic, replayable):

```
rule_evaluations(id, adventure_id, rule_key, ruleset_version,
                 subject_ids uuid[], state(compatible|possibly|not_recommended|unknown),
                 detail jsonb, evaluated_at)
```

Products (thin in V1) and reviews:

```
products(id, brand, model, category_id, activity_key, generation,
         specs jsonb,             -- OBJECTIVE ONLY
         source(manual|curated|import), created_by, created_at)
product_variants(id, product_id, size, colorway, weight_g, attributes jsonb)
reviews(id, user_id, product_id?, gear_item_id?, activity_key,
        rating, durability, performance, fit, pros text[], cons text[], body,
        context jsonb,           -- location, duration, distance, conditions
        verified_ownership, created_at)
```

Ops — and the §28 separation, made structural:

```
ai_runs(...)                       -- identical to VoyageOS
ai_outputs(id, subject_type, subject_id, task, payload jsonb,
           model, prompt_version, created_at)
```

**`products.specs` is objective and human-entered. `ai_outputs` is generated.
They are never the same column** — that is §28's "never let AI silently
overwrite factual specs", enforced by the schema rather than by care.

Indexing: GIN on `gear_items.attributes` and `adventures.attributes`; btree on
the foreign keys and on `(user_id, status)` for the locker list.

RLS: enabled and **written correctly from 0001**, unlike VoyageOS. The API seam
is still the enforcement point, but a single-player app has no excuse for
policies that are wrong on the day they're written.

### Screen map — 5 tabs (§18)

- **HOME** — greeting · NEXT ADVENTURE card · upcoming · locker summary · gear
  needing attention · recent gear. (New-releases slot is empty in V1, by §0.4.)
- **ADVENTURES** — list → **Adventure detail** (Overview / Pack / Gear Match /
  Weather) → **New Adventure wizard**: activity → subtype → location → dates →
  trail-running form → *Generate Smart Pack*.
- **GEAR** — locker list (filter: category, status, favorite) → **Gear item
  detail** (Specs / Usage / Maintenance / Compatibility) → **Add gear**: search
  product · **manual entry** (the common path in V1).
- **DISCOVER** — designed, deliberately empty in V1 with an honest empty state.
- **PROFILE** — account, units, notifications, subscription, privacy.
- **Ask Outdoor AI** — persistent, over any screen. VoyageOS already has the
  pattern for this: `RedeemSheet` renders *outside* the navigator and
  `PlansContext` passes an opener through context rather than through navigation
  params (functions in navigation state break serialisation).

### The V1 loop (§25), for Trail Running only

`DISCOVER → OWN → PLAN → SELECT → PACK → VERIFY → USE → REVIEW → MAINTAIN`

1. Add gear — manual entry, activity-specific fields from the JSONB schema.
2. Create adventure — Oman 100M: 160 km, 9,000 m+, ~30 h, mountain/technical.
3. Generate Smart Pack — **deterministic** classification into
   REQUIRED/RECOMMENDED/OPTIONAL/NOT NEEDED/MISSING + WARNINGS, from adventure
   attributes × weather × locker × compatibility × gear health. **Then** one
   model call for the narrative wrapper.
4. Select → pack → verify. Readiness check before departure.
5. After the run: log usage (distance, conditions) → gear health recalculates →
   contextual review.

### External services required

| Service | Status |
|---|---|
| Open-Meteo forecast + geocoding | Free, no key. **Already implemented.** |
| MET Norway | Free fallback, needs UA. **Already implemented.** |
| Open-Meteo Elevation (or Open-Topo) | Free. New, small. |
| Nominatim | Already used in `guide/geocode.py`; 1 req/s, background-only. |
| Anthropic API | Same key, new gateway fork. |
| Supabase | **New project.** |
| Render | **New Starter service ($7/mo).** |
| RevenueCat + Expo Push | New app, same plumbing. |
| Product data | **None in V1** (§0.4). Phase 5 research spike. |

---

## 5. Technical risks

1. **Dark mode and offline have nothing to inherit.** Both are §19/§20
   requirements with zero prior art in VoyageOS. Retrofitting a dark palette
   means revisiting every screen written before it. → Build both into Phase 1.
2. **Activity-schema drift.** The whole "no rework for Phase 7" claim rests on a
   JSONB attribute system that has only ever been exercised by one activity.
   → Write the **fishing schema as a test fixture in Phase 1** and assert the
   loader, validator and renderer handle it, even though no UI shows it. A
   schema proven by one consumer is not proven.
3. **In-process scheduler.** Inherited from VoyageOS; blocks running more than
   one web instance. Decide in Phase 1.
4. **Gear-health thresholds are genuinely uncertain.** Trail shoe lifespan
   (500–800 km is folklore, and varies by foam, runner mass and terrain) cannot
   be stated as a failure point — §12 says so explicitly. → The engine emits a
   **band plus an inspection prompt**, never a date. This is a correctness
   requirement, not a copy one.
5. **Race mandatory kit is authoritative external data** that changes per event
   and per year. → User-entered or admin-curated only. Never AI-generated (§24).
6. **Ops surface doubles.** Second Supabase project, second Render service,
   second RevenueCat app, second EAS project — each with its own migrations, key
   rotations, webhook environments and build cuts. `BUILD.md` is 31 KB of
   hard-won process for *one* app. Budget for duplicating the discipline, not
   just the code.
7. **AI cost is unmeasured for this shape.** The `$0.50`/user/day default was
   tuned for trip guides. A Smart Pack narrative over a full gear locker plus a
   conversational Ask Outdoor AI is a different prompt size. → Measure in Phase
   3/4 before fixing the cap, and keep `ai_runs` from the first commit.
8. **`app/voyage-outdoor/` is a stray empty git repo** inside the VoyageOS
   working tree (untracked, no commits, no remote). It is not the new project
   and should be deleted before Phase 1 to avoid a nested-repo mess.

---

## 6. Implementation sequence

Follows §27, with three amendments marked **[+]**.

- **Phase 0 — Audit.** This document. *Awaiting approval.*
- **Phase 1 — Foundation.** New repo · Supabase project · Render Starter service
  · app shell (5 tabs) · auth · profile · activity registry with the trail
  running schema · gear categories · Gear Locker (list, detail, manual add,
  edit, retire) · `ai_gateway` fork · `ai_runs` from the first commit.
  **[+]** light/dark token pair in `theme.ts` from commit one.
  **[+]** persisted cache under the API client from commit one.
  **[+]** the fishing attribute-schema fixture test.
- **Phase 2 — Adventures.** Adventure CRUD · trail-running form · adventure
  dashboard · weather fork wired to adventures.
- **Phase 3 — Smart Pack.** The **deterministic** rules engine (classification +
  warnings), compatibility engine, gear-health thresholds, pack states,
  readiness score. No model calls in this phase at all.
- **Phase 4 — AI.** Ask Outdoor AI + the Smart Pack narrative + Gear Match
  explanations, all on top of Phase 3's structured output.
- **Phase 5 — Discover.** Product-data sourcing spike (§0.4) → product database →
  reviews → new releases.
- **Phase 6 — Polish.** Offline depth, notifications, performance, accessibility,
  glove-usable targets, testing. (Dark mode is no longer in this phase.)
- **Phase 7 — Second activity + community.** Fishing or fly fishing, which is
  what actually proves the schema generalises. Community only after the UGC and
  moderation questions blocking VoyageOS's traveller posts are resolved.

Build in-repo with real commits. No patch-file handoffs (§1).

---

**Stop point.** Phase 1 does not begin without approval, per §27 and §30.
