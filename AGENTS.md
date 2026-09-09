# Voyage Outdoor — working rules

## Expo HAS CHANGED

Read the exact versioned docs at https://docs.expo.dev/versions/v54.0.0/ before
writing any app code. This is SDK 54; the shape of half the API surface moved
between 50 and 54 and answering from memory produces code that looks right and
does not run.

## The line that decides everything

**Deterministic code decides. AI explains.**

The compatibility engine (§11), gear health (§12), Gear Match ranking (§10) and
the Smart Pack REQUIRED/RECOMMENDED/MISSING classification (§8) are pure,
versioned, tested Python. No model is in any decision path. A model may take an
engine's structured output and write a sentence about it — never the reverse.

Two mechanisms enforce this rather than good intentions:

- every model payload passes a `sanitize_*` whitelist gate, so model output
  cannot introduce a field;
- where an engine and a model both have an opinion, the engine writes last and
  the divergence is counted.

Both are lifted from VoyageOS, where they were learned the expensive way.

## Objective vs generated

`products.specs` is human-entered fact. `ai_outputs` is generated text. They are
different tables and must never merge. AI never silently overwrites a spec.

## Schema

Activity-specific fields live in JSONB (`gear_items.attributes`,
`adventures.attributes`), validated at the API boundary with pydantic against
the registry in `api/activities/`. **Never a CHECK constraint enumerating a
taxonomy** — VoyageOS's `items.category` is a ten-value CHECK that collapsed all
outdoor equipment into `activity_gear`, and it cannot be widened without a
migration. CHECK constraints are for closed state machines (`status`), not for
things that grow.

## Build discipline

In-repo, real commits. No patch-file handoffs — VoyageOS lost three "shipped"
features that way.

## Not VoyageOS

Separate Supabase project, separate Render service, separate auth, separate
RevenueCat app. No shared tables, no shared migrations. The `ADVENTURE` object
is not `TRIP` and must not learn to be.
