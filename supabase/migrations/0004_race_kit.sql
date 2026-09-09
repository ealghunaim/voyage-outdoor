-- 0004 — race kit imports (Phase 4, §24)
--
-- Mandatory equipment is AUTHORITATIVE EXTERNAL DATA. It outranks every rule in
-- the pack engine, and the engine marks each of its lines critical. Data with
-- that much authority needs to say where it came from, so this table stores the
-- source alongside the extraction: the URL, the SHA-256 of the bytes actually
-- fetched, and the date they were fetched.
--
-- WHY IT IS A SEPARATE TABLE and not columns on `adventures`:
--
--   * A draft exists before any adventure does. The common flow is "import the
--     kit, see what it says, then attach it" — and someone importing a list
--     they decide not to use should not have created an adventure to do it.
--   * The provenance is about the IMPORT, not about the race. Re-importing next
--     year's edition produces a second row, and both remain readable; a column
--     would have been overwritten and the question "what did we tell them last
--     March" would have no answer.
--   * `adventures.attributes` is validated against the activity registry, which
--     drops keys it does not know. Provenance stored there would be silently
--     discarded on the next save — a failure that leaves no trace at all.
--
-- THE ACCEPTED LIST IS STORED SEPARATELY from the extracted one. A human ticks
-- items on the way in, and the difference between what a model read and what a
-- person accepted is the audit trail for §24's "allow manual verification". If
-- a kit line later turns out to be wrong, this is where you find out whether it
-- was extracted wrong or accepted anyway.

create table public.race_kit_imports (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,

  -- Set when the draft is accepted onto an adventure. Nullable throughout the
  -- draft's life; `on delete set null` keeps the provenance record readable
  -- after the adventure it fed is deleted.
  adventure_id uuid references public.adventures(id) on delete set null,

  status text not null default 'draft'
    check (status in ('draft','accepted','discarded')),

  -- ── where it came from ──────────────────────────────────────────────────
  source_kind text not null check (source_kind in ('url','paste')),
  source_url text,                    -- the FINAL url, after redirects
  source_sha256 text,                 -- of the bytes fetched; null for a paste
  source_chars int,
  fetched_at timestamptz not null default now(),

  -- ── what the page said ──────────────────────────────────────────────────
  race_name text,
  edition text,
  event text,
  -- The full extraction, as returned: items with their conditions, the
  -- recommended-but-not-required list, and the model's note about how it read
  -- the page. Kept whole rather than flattened to a text[] so that a
  -- disagreement later can be settled against what was actually extracted.
  extracted jsonb not null default '{}',

  -- ── what the human took ─────────────────────────────────────────────────
  accepted_items jsonb,               -- text[] of the lines written onto the adventure
  accepted_at timestamptz,

  -- ── how it was read ─────────────────────────────────────────────────────
  model text,
  prompt_version text,
  stats jsonb not null default '{}',  -- chars read, narrowed?, cost, latency

  created_at timestamptz not null default now()
);

create index on public.race_kit_imports (user_id, created_at desc);
create index on public.race_kit_imports (adventure_id);

alter table public.race_kit_imports enable row level security;

create policy "own race kit imports" on public.race_kit_imports
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());
