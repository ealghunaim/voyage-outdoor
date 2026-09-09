-- Run this AFTER 0001 and 0002. It changes nothing.
--
-- Three things can go wrong in a way the migrations themselves will not report:
-- a table that did not get created because an earlier statement failed and the
-- rest ran anyway, RLS left off on a table holding user data, and the seed rows
-- missing so every activity lookup returns nothing. One query each.

-- 1. Every table, and whether RLS is on. Expect 14 rows, all rls = true.
select c.relname as table_name,
       c.relrowsecurity as rls,
       (select count(*) from pg_policies p
        where p.schemaname = 'public' and p.tablename = c.relname) as policies
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r'
order by c.relname;

-- 2. The seeded reference data. Expect 4 activities (trail_running built) and
--    19 gear categories.
select 'activities' as what, count(*) as rows from public.activities
union all
select 'activities built', count(*) from public.activities where built
union all
select 'gear_categories', count(*) from public.gear_categories
union all
select 'categories universal', count(*) from public.gear_categories
  where activity_key is null;

-- 3. attribute_schema is still empty at this point — scripts/seed_reference.py
--    fills it from the Python registry. Expect 4 rows of '{}'; after the seed
--    script, trail_running should be large and the other three non-empty.
select key, built, length(attribute_schema::text) as schema_chars
from public.activities order by sort;
