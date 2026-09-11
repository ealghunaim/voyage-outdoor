-- 0006 — fishing gear categories (Phase 7)
--
-- The second activity, and the first real test of the claim in §3 that hiking,
-- fishing and fly fishing would not need rework. What it cost is recorded in
-- api/engines/tackle.py: the attribute model held without a structural change,
-- and the compatibility ENGINE did not — fishing's rules are gear↔gear
-- (ROD↔REEL, REEL↔LINE, LINE↔LEADER per §11) where trail running's are all
-- gear↔adventure, so a new rule shape was needed beside the old one.
--
-- `built` is flipped by scripts/seed_reference.py from the registry's BUILT
-- set, not here — the registry is the original and this table is the copy (see
-- registry.py). This migration only adds the rows that copy needs to point at.
--
-- NOTE ON `first_aid`, `safety` AND `accessories`: already present as universal
-- categories from 0002, and reused unchanged. A fishing-specific duplicate of
-- "first aid" would be a second category meaning the same thing, which is how a
-- taxonomy starts disagreeing with itself.

insert into public.gear_categories (key, name, activity_key, sort) values
  ('rod',             'Rods',              'fishing', 10),
  ('reel',            'Reels',             'fishing', 20),
  ('line',            'Main Line',         'fishing', 30),
  -- ITS OWN CATEGORY, not a kind of line. §11 names LINE↔LEADER as a
  -- relationship in its own right, and the leader is the part that touches the
  -- fish — for GT it is what coral cuts first.
  ('leader',          'Leaders',           'fishing', 40),
  ('lure',            'Lures',             'fishing', 50),
  ('terminal_tackle', 'Hooks & Terminal',  'fishing', 60),
  ('tools',           'Tools',             'fishing', 70),
  ('sun_protection',  'Sun Protection',    'fishing', 80)
on conflict (key) do nothing;
