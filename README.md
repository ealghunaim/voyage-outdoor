# Voyage Outdoor

The operating system for outdoor gear and adventures.

**Tell the app what you are doing. It knows what you own. It helps you decide
what to bring.**

A spin-off of [VoyageOS](https://github.com/ealghunaim/VoyageOS), sharing its
engineering lineage and nothing else — separate Supabase project, separate
service, separate auth, separate store listing. See
[`docs/VOYAGE-OUTDOOR-PHASE-0-AUDIT.md`](docs/VOYAGE-OUTDOOR-PHASE-0-AUDIT.md)
for what was inherited, what was deliberately not, and why.

## Where this is

**Phase 1 — Foundation.** V1 activity is **Trail Running only**; hiking, fishing
and fly fishing exist in the schema so the architecture is exercised by more
than one consumer, and have no UI.

| | |
|---|---|
| ✅ | Schema (0001, 0002), activity registry, attribute validation |
| ✅ | Identity, profile, preferences, the two request gates |
| ✅ | Gear Locker API — items, usage, maintenance |
| ✅ | Expo app — auth, five tabs, locker list/detail/form, light + dark |
| ⬜ | Apply the migrations to Supabase and run the app against it |
| ⬜ | Phase 2 Adventures · Phase 3 Smart Pack · Phase 4 AI |

Two amendments from the audit are already in, because both are cheap now and
expensive in Phase 6: the theme ships as a **light/dark token pair** (VoyageOS
is light-only and every screen would need revisiting), and a **persisted cache**
sits under the API client so screens render from disk before the network answers
(VoyageOS has none — every screen fetches on mount).

## Layout

```
api/            FastAPI. activities/ is the registry; core/ is config, db,
                auth and the ownership seam; gear/ is the locker.
app/            Expo SDK 54 · React Native 0.81 · React Navigation v7
supabase/       plain-SQL migrations, numbered, run in order
scripts/        seed_reference.py pushes registry → activities.attribute_schema
docs/           the Phase 0 audit
```

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # fill in SUPABASE_SERVICE_KEY
.venv/bin/python -m pytest api/tests -q
.venv/bin/uvicorn api.main:app --reload
```

The test suite needs no database and no keys — the gates refuse before anything
touches Supabase, which is why they are fast and why a misconfigured gate cannot
hide behind a connection error.

That speed is also its blind spot, so there is a second kind of test that runs
against the real thing:

```bash
.venv/bin/uvicorn api.main:app --port 8000 &
.venv/bin/python -m scripts.smoke_test
```

30 checks over the whole Phase 1 loop — sign in, own, refuse, use, patch,
filter, and confirm one account cannot see another's gear. It creates two
throwaway accounts and deletes them at the end, which also proves the cascade
from `auth.users` down through the locker works. Development projects only.

Migrations are applied by pasting them into the Supabase SQL editor, in order,
then running `.venv/bin/python -m scripts.seed_reference`.

The app:

```bash
cd app && npm install
npx expo start                  # needs app.json → extra filled in first
npm run typecheck && npx eslint .
```

`app.json → extra` needs `supabaseAnonKey` and, for a deployed build, `apiUrl`
and `appKey`. Until then the sign-in screen says exactly what is missing rather
than failing as a network error.

## The rules that are not negotiable

Read [`AGENTS.md`](AGENTS.md) before changing anything. The short version:

- **Deterministic code decides, AI explains.** No model sits in the
  compatibility, gear-health, Gear Match or pack-classification path.
- **Objective and generated data live in different tables.** `products.specs`
  is fact; `ai_outputs` is generated; they never merge.
- **No CHECK constraint on a taxonomy.** VoyageOS's ten-value `items.category`
  is why every piece of outdoor gear it stores is filed as `activity_gear`.
- **Attributes are validated at the API boundary**, against the Python
  registry — never by a database constraint that would need rewriting to add an
  activity.
