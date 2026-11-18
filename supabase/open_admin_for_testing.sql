-- TEMPORARY, FOR TESTING ONLY. Lets ANYONE (no sign-in) read everything and add / change / delete
-- risk areas and emergency services. Pair it with ADMIN_OPEN: true in js/config.js.
-- Undo: run supabase/lock_admin.sql and set ADMIN_OPEN: false.
drop policy if exists "TEMP open read risk"   on public.risk_areas;
drop policy if exists "TEMP open insert risk" on public.risk_areas;
drop policy if exists "TEMP open update risk" on public.risk_areas;
drop policy if exists "TEMP open delete risk" on public.risk_areas;
create policy "TEMP open read risk"   on public.risk_areas for select to anon, authenticated using (true);
create policy "TEMP open insert risk" on public.risk_areas for insert to anon, authenticated with check (true);
create policy "TEMP open update risk" on public.risk_areas for update to anon, authenticated using (true) with check (true);
create policy "TEMP open delete risk" on public.risk_areas for delete to anon, authenticated using (true);

drop policy if exists "TEMP open insert svc" on public.emergency_services;
drop policy if exists "TEMP open update svc" on public.emergency_services;
drop policy if exists "TEMP open delete svc" on public.emergency_services;
create policy "TEMP open insert svc" on public.emergency_services for insert to anon, authenticated with check (true);
create policy "TEMP open update svc" on public.emergency_services for update to anon, authenticated using (true) with check (true);
create policy "TEMP open delete svc" on public.emergency_services for delete to anon, authenticated using (true);
