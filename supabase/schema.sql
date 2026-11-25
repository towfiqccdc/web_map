-- ============================================================
-- Road-safety risk areas  —  run this ONCE in Supabase
-- (Supabase dashboard -> SQL Editor -> New query -> paste -> Run)
-- ============================================================

-- 1) The table that stores every risk area -------------------
create table if not exists public.risk_areas (
  id          uuid primary key default gen_random_uuid(),
  title       text not null check (char_length(title) <= 200),
  type        text not null check (type in ('accident', 'violence', 'other')),
  severity    smallint not null default 2 check (severity between 1 and 3),  -- 1 low, 2 medium, 3 high
  lat         double precision not null check (lat between 20.5 and 26.7),   -- Bangladesh only
  lng         double precision not null check (lng between 88.0 and 92.8),
  radius_m    integer not null default 2000 check (radius_m between 200 and 20000),
  source      text not null check (source in ('news', 'manual')),
  source_url  text unique,                    -- news link; unique so one article is never added twice
  place_text  text,                           -- the place name the news job matched (for you to verify)
  title_original text,                        -- Bangla headline, when the title above was translated to English
  status      text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'held')),   -- held = failed the automatic checks, never shown
  happened_on date,
  confidence  text check (confidence in ('high','medium','low')),   -- result of the news job's verification checks
  evidence    text,                           -- the sentence that names the place
  checks      text,                           -- which checks passed / warned
  body_read   boolean not null default false, -- true when the article text itself was read
  created_at  timestamptz not null default now(),
  expires_at  timestamptz                     -- after this the risk stops affecting routes
);

create index if not exists risk_areas_status_idx on public.risk_areas (status, expires_at);

-- 2) Who is an administrator ---------------------------------
create table if not exists public.admins (
  email text primary key
);

create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.admins
    where lower(email) = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;

-- Only signed-in users may call it (anonymous visitors cannot).
revoke execute on function public.is_admin() from public, anon;
grant execute on function public.is_admin() to authenticated;

-- 3) Security rules (Row Level Security) ---------------------
alter table public.risk_areas enable row level security;
alter table public.admins     enable row level security;   -- no policies = nobody can read/write it from the website

-- Everyone (the public map) may read ONLY approved, not-yet-expired rows
drop policy if exists "public reads approved" on public.risk_areas;
create policy "public reads approved" on public.risk_areas
  for select to anon, authenticated
  using (status = 'approved' and (expires_at is null or expires_at > now()));

-- Logged-in admins may read everything (including pending / rejected)
drop policy if exists "admin reads all" on public.risk_areas;
create policy "admin reads all" on public.risk_areas
  for select to authenticated
  using (public.is_admin());

-- Only admins may add / change / delete
drop policy if exists "admin inserts" on public.risk_areas;
create policy "admin inserts" on public.risk_areas
  for insert to authenticated
  with check (public.is_admin());

drop policy if exists "admin updates" on public.risk_areas;
create policy "admin updates" on public.risk_areas
  for update to authenticated
  using (public.is_admin())
  with check (public.is_admin());

drop policy if exists "admin deletes" on public.risk_areas;
create policy "admin deletes" on public.risk_areas
  for delete to authenticated
  using (public.is_admin());

-- The daily news job uses the secret "service_role" key, which bypasses these rules,
-- so it can insert 'pending' rows. The public website key can never write anything.

-- 4) MAKE YOURSELF AN ADMIN  (change the email, then run this line too)
-- insert into public.admins (email) values ('your-email@example.com') on conflict do nothing;
