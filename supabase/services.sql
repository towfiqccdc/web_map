-- Emergency services (hospital / police / fire / fuel) that admins can add, edit and delete.
-- Run once in Supabase -> SQL Editor. Safe to run again.

create table if not exists public.emergency_services (
  id         uuid primary key default gen_random_uuid(),
  type       text not null check (type in ('hospital','police','fire','fuel')),
  name       text not null check (char_length(name) between 2 and 150),
  lat        double precision not null check (lat between 20.5 and 26.7),
  lng        double precision not null check (lng between 88 and 92.8),
  phone      text check (phone is null or char_length(phone) <= 30),
  icon       text check (icon is null or char_length(icon) <= 8),   -- optional emoji that overrides the default for the type
  created_at timestamptz not null default now()
);

alter table public.emergency_services enable row level security;

drop policy if exists "public reads services" on public.emergency_services;
create policy "public reads services" on public.emergency_services
  for select to anon, authenticated using (true);

drop policy if exists "admin inserts services" on public.emergency_services;
create policy "admin inserts services" on public.emergency_services
  for insert to authenticated with check (public.is_admin());

drop policy if exists "admin updates services" on public.emergency_services;
create policy "admin updates services" on public.emergency_services
  for update to authenticated using (public.is_admin()) with check (public.is_admin());

drop policy if exists "admin deletes services" on public.emergency_services;
create policy "admin deletes services" on public.emergency_services
  for delete to authenticated using (public.is_admin());

-- Starting list (copied from js/data.js). Only inserted while the table is empty.
insert into public.emergency_services (type, name, lat, lng)
select * from (values
  ('police','Khatihata Highway Police Station',24.059018788035374,91.11603961507865),
  ('police','Sarail Police Station',24.070875737908917,91.11277870995212),
  ('police','Bhairab Police Station',24.0569079628927,90.97795869029738),
  ('police','Itakhola Police Fari',23.98174307078492,90.7323280837806),
  ('police','Narsingdi Model Police Station',23.926825434801064,90.70949708559081),
  ('police','Madhabdi Police Station',23.854099918307323,90.6672398983058),
  ('police','Cantonment Police Station',23.82505076536148,90.4058611383411),
  ('hospital','Brahmanbaria Medical College Hospital',24.00519040047586,91.10922411311577),
  ('hospital','Life Care Hospital',23.934285486270763,90.71534666216661),
  ('hospital','K.P.S General Hospital Ltd.',23.844249880573177,90.55219795069064),
  ('hospital','Kurmitola Multicare Specialized Hospital',23.820620542441734,90.40874951970548),
  ('hospital','Continental Hospital PLC',23.807018377308054,90.41538959345425),
  ('hospital','Evercare Hospital, Dhaka',23.811244576146365,90.43101049067751),
  ('fire','Nandan Kanan Fire Station',23.97720439462849,91.10945328823468),
  ('fire','Ashuganj Fire Station',24.045354029558222,91.00759176498634),
  ('fire','Bhairab Fire Station',24.065979608591345,90.97779085617938),
  ('fire','Raipura Fire Station',24.010340361834203,90.86386058068582),
  ('fire','Fire Service, Shibpur',24.02961078497828,90.73548316856287),
  ('fire','Fire Service & Civil Defense Station',23.921935357040347,90.71935252894778),
  ('fire','Madhabdi Fire Station',23.853220063110946,90.68211241963287),
  ('fire','Fire Service & Civil Defence Station Purbachal',23.841858724413882,90.48349495429832),
  ('fuel','Fuel Station 1',24.02501146920914,91.11127064792856),
  ('fuel','Fuel Station 2',24.051150676207833,91.11353257650218),
  ('fuel','Fuel Station 3',24.04977559218569,91.10502685677753),
  ('fuel','Fuel Station 4',24.043983615231653,91.04219294115114),
  ('fuel','Fuel Station 5',24.0402520838857,91.0045876621916),
  ('fuel','Fuel Station 6',24.043955754373144,90.85324219011409),
  ('fuel','Fuel Station 7',24.02247689904458,90.8114433273466),
  ('fuel','Fuel Station 8',23.98448853702763,90.74261964136933),
  ('fuel','Fuel Station 9',23.961120271142633,90.71759674139074),
  ('fuel','Fuel Station 10',23.855335253098726,90.66110990236403)
) as v(type, name, lat, lng)
where not exists (select 1 from public.emergency_services);
