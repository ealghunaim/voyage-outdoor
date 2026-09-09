-- Voyage Outdoor · 0002 reference data
--
-- WHAT IS SEEDED HERE vs. WHAT IS SEEDED FROM PYTHON, and why it is split:
--
--   here          activity rows (key, name, built, sort) and the gear category
--                 taxonomy. Static, rarely changes, and useful to have in the
--                 database even when the API is not running.
--
--   seed script   activities.attribute_schema, pushed from api/activities/ by
--                 scripts/seed_reference.py. The registry is the ONE source of
--                 truth for field shapes because pydantic validates against it
--                 on every write; a schema duplicated in SQL would be a second
--                 opinion, and the two would disagree within a month.
--
-- built = false means DEFINED, NOT BUILT. Three activities are here so the
-- attribute model is exercised by more than one consumer before it is called
-- general (Master Prompt §3, and audit risk #2). No UI reaches them.

insert into public.activities (key, name, built, sort) values
  ('trail_running', 'Trail Running', true,  10),
  ('hiking',        'Hiking',        false, 20),
  ('fishing',       'Fishing',       false, 30),
  ('fly_fishing',   'Fly Fishing',   false, 40)
on conflict (key) do nothing;

-- ── gear categories ─────────────────────────────────────────────────────────
--
-- activity_key null = applies everywhere. A headlamp is a headlamp whether you
-- are running a night leg or walking back to a car, and duplicating it per
-- activity would mean a locker that lists the same torch four times.

insert into public.gear_categories (key, name, activity_key, sort) values
  -- universal
  ('headlamp',      'Headlamps & Lighting',  null, 100),
  ('navigation',    'Navigation',            null, 110),
  ('electronics',   'Electronics & Power',   null, 120),
  ('first_aid',     'First Aid',             null, 130),
  ('safety',        'Safety & Emergency',    null, 140),
  ('eyewear',       'Eyewear',               null, 150),
  ('headwear',      'Headwear',              null, 160),
  ('gloves',        'Gloves',                null, 170),
  ('jacket',        'Shells & Jackets',      null, 180),
  ('accessories',   'Accessories',           null, 999),

  -- trail running
  ('shoes',           'Trail Shoes',        'trail_running', 10),
  ('socks',           'Socks',              'trail_running', 20),
  ('vest',            'Vests & Packs',      'trail_running', 30),
  ('poles',           'Poles',              'trail_running', 40),
  ('hydration',       'Hydration',          'trail_running', 50),
  ('nutrition',       'Nutrition',          'trail_running', 60),
  ('apparel_top',     'Tops',               'trail_running', 70),
  ('apparel_bottom',  'Shorts & Tights',    'trail_running', 80),
  ('gaiters',         'Gaiters',            'trail_running', 90)
on conflict (key) do nothing;
