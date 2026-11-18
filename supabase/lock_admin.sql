-- Puts the admin protection back: only signed-in admins can change data again.
drop policy if exists "TEMP open read risk"   on public.risk_areas;
drop policy if exists "TEMP open insert risk" on public.risk_areas;
drop policy if exists "TEMP open update risk" on public.risk_areas;
drop policy if exists "TEMP open delete risk" on public.risk_areas;
drop policy if exists "TEMP open insert svc" on public.emergency_services;
drop policy if exists "TEMP open update svc" on public.emergency_services;
drop policy if exists "TEMP open delete svc" on public.emergency_services;
