-- 0005 — reviews of gear you own (Phase 5, §14, §15)
--
-- A REVIEW IS ATTACHED TO A LOCKER ITEM, NOT TO A PRODUCT, and that is a
-- consequence of §0.4 rather than a shortcut. There is no live product database
-- in V1; the catalog is admin-entered and thin. Reviews of a catalog that
-- barely exists would be a feature with nothing behind it. Reviews of gear
-- somebody actually owns have everything behind them already: the usage log,
-- the maintenance history, and the adventures it was carried on.
--
-- `product_id` is copied here at write time rather than joined through
-- gear_items. Two reasons, both about the future the brief plans for:
--
--   * A review written before its item was linked to a catalog product should
--     still aggregate once someone links it.
--   * Unlinking a locker item later must not silently remove its review from a
--     product's average — that is data disappearing because of an edit
--     somewhere else.
--
-- THE CONTEXT IS SNAPSHOTTED, NOT COMPUTED ON READ. "Five stars" after 20 km
-- and "five stars" after 800 km are different statements, and the second is the
-- one worth reading. If the context were joined live, every review would
-- silently re-describe itself every time its owner logged another run, and a
-- review written at 200 km would eventually claim to have been written at 900.
-- §15 calls these "contextual reviews"; this column is the context.

create table public.gear_reviews (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  gear_item_id uuid not null references public.gear_items(id) on delete cascade,
  product_id uuid references public.products(id) on delete set null,

  rating int not null check (rating between 1 and 5),
  body text,

  -- Distance, sessions, duration, the adventures it was carried on, and the
  -- gear-health band at the moment of writing — with the ruleset versions that
  -- produced them, so an old review can be read against the rules it was
  -- written under rather than today's.
  context jsonb not null default '{}',

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  -- ONE REVIEW PER ITEM PER PERSON. A second one is an edit, not a new
  -- opinion — otherwise a locker item accumulates a thread of one person
  -- arguing with themselves, and any average over it is weighted by whoever
  -- wrote most often.
  unique (user_id, gear_item_id)
);

create index on public.gear_reviews (user_id, updated_at desc);
create index on public.gear_reviews (product_id) where product_id is not null;

alter table public.gear_reviews enable row level security;

create policy "own reviews" on public.gear_reviews
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());
