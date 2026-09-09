-- Run AFTER 0001 and 0002. Changes nothing.
--
-- ONE RESULT SET, deliberately. This was three separate queries and the
-- Supabase SQL editor shows only the last one, so two thirds of the answer was
-- invisible — the check silently checked less than it claimed to. A verifier
-- you have to scroll to is a verifier that reports what happened to be on
-- screen.
--
-- The `ok` column compares got against expect. Row 8 fails until
-- scripts/seed_reference.py has run, and that is the point of having it here:
-- it is the one step the migrations cannot do for themselves.

with tables as (
  select c.relname,
         c.relrowsecurity as rls,
         (select count(*) from pg_policies p
          where p.schemaname = 'public' and p.tablename = c.relname) as policies
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public' and c.relkind = 'r'
),
checks(ord, what, got, expect) as (
  select 1, 'tables created',
         count(*)::text, '14' from tables
  union all
  select 2, 'RLS enabled',
         count(*) filter (where rls)::text, '14' from tables
  union all
  select 3, 'tables missing RLS',
         coalesce(string_agg(relname, ', ') filter (where not rls), 'none'), 'none'
    from tables
  union all
  -- ai_runs and ai_outputs carry RLS with NO policy on purpose: the service key
  -- reads them and nobody else does. Any OTHER table with zero policies is a
  -- table the anon key cannot reach at all, which is a bug rather than a choice.
  select 4, 'tables with RLS but no policy',
         coalesce(string_agg(relname, ', ') filter (
           where policies = 0 and relname not in ('ai_runs', 'ai_outputs')), 'none'),
         'none'
    from tables
  union all
  select 5, 'activities', count(*)::text, '4' from public.activities
  union all
  select 6, 'activities built', count(*)::text, '1'
    from public.activities where built
  union all
  select 7, 'gear categories', count(*)::text, '19' from public.gear_categories
  union all
  select 8, 'categories universal', count(*)::text, '10'
    from public.gear_categories where activity_key is null
  union all
  select 9, 'orphan categories', count(*)::text, '0'
    from public.gear_categories c
   where c.activity_key is not null
     and not exists (select 1 from public.activities a where a.key = c.activity_key)
  union all
  select 10, 'attribute_schema seeded  (needs seed_reference.py)',
         count(*) filter (where length(attribute_schema::text) > 2)::text, '4'
    from public.activities
)
select ord as step,
       what,
       got,
       expect,
       case when got = expect then 'ok' else 'CHECK' end as ok
from checks
order by ord;
