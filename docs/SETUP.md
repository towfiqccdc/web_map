# Setting up the live risk database (one time, about 20 minutes)

What you are building: the news job and the 🔒 Admin button on the main map put **risk areas** into a free online
database (Supabase). The public map reads the **approved** ones and, when someone types
*From → To*, picks the route with the fewest reported risks.

```
news (daily)  ──▶ [pending] ──you approve──▶ [approved] ──▶ map: From → To  ──▶ safest route
map page → 🔒 Admin (manual, instantly approved) ──────────┘
```

## 1. Create the database (Supabase, free)
1. Go to https://supabase.com → sign up → **New project**. Pick a region near Bangladesh (Singapore is closest). Save the database password somewhere safe.
2. Wait until the project is ready, then open **SQL Editor → New query**.
3. Open the file `supabase/schema.sql` from this repo, copy **everything**, paste it, press **Run**. It should say "Success".
4. In the same editor, run this one line (put YOUR email in it):
   `insert into public.admins (email) values ('you@example.com') on conflict do nothing;`
5. Go to **Authentication → Users → Add user → Create new user**. Use the same email, choose a password, and tick **Auto Confirm User**. This is your admin login.

## 2. Connect the website
1. In Supabase open **Project Settings → API**. Copy the **Project URL** and the **anon public** key.
2. In GitHub open `js/config.js`, click the pencil ✏️ (edit), paste them between the quotes, and **Commit changes**.
   *(The anon key is meant to be public. It can only read approved risk areas.)*

## 3. Connect the daily news job
1. In Supabase **Project Settings → API**, copy the **service_role** key. **This one is a secret — never put it in a file.**
2. In GitHub open your repo → **Settings → Secrets and variables → Actions → New repository secret**. Add two secrets:
   - `SUPABASE_URL` = the Project URL
   - `SUPABASE_SERVICE_KEY` = the service_role key
3. Open the **Actions** tab → **Daily news check** → **Run workflow**. After a minute open the run: it lists which news feeds worked and how many pending items were added. Feeds that fail are just reported; edit `news/feeds.txt` to remove or replace them.

It then runs by itself every day at 06:30 Bangladesh time.

## 4. Every day
1. Open the map and tap **🔒 Admin** (top right). Sign in with your admin email and password. There is no separate admin page.
2. **Review** (pending) shows what the news job found. Click one, check the map location (drag the marker if it is wrong) and the news link, then **Approve** or **Reject**.
3. **New** lets you tap the map and add a risk yourself; it goes live immediately.
4. **Active** lets you edit, stop or delete a risk. Risks stop counting automatically on their end date (news: 30 days, manual: 90 days — you can change the date).

## How the safest route is chosen
- The map asks the routing service for the main route and its alternatives.
- Each route gets a score: every approved risk within its radius of the road adds its severity (1–3), counted at full weight for 7 days, 70% up to 30 days, 40% after that.
- The route with the lowest score is marked **Lowest risk**. If two are equal, the faster one wins.
- "No reported incidents" only means nothing has been reported — it is **not** a guarantee.

## Things to know
- **News matching is a guess.** It reads headlines and summaries, finds a place name and looks it up on a map. That is why nothing goes live until you approve it.
- **Only English news** is searched for now.
- **Free services have limits.** The free route service (OSRM demo) and place search (OpenStreetMap Nominatim) have no guarantees; for heavy use, host or pay for them (`js/config.js`).
- **Free Supabase projects pause** after about a week with no activity; the daily job normally keeps it awake.
- **GitHub switches off scheduled jobs** in a repo that has had no commits for 60 days. If that happens, press **Enable workflow** on the Actions tab.
- All new `js/` files are served by your website host (GitHub Pages). The Render server only serves the pages it already did.

## Base map and live traffic
- The base map is **Esri World Imagery** (satellite, no labels) so the markers and routes stand out. The **Street map** button switches to a labelled map. Esri requires its attribution to stay visible (it is shown bottom right) and has its own terms for heavy use.
- **Traffic**: with no key, the button opens Google Maps traffic for the area you are looking at. For a live layer *on* this map, get a free key from a traffic tile provider such as TomTom and paste the tile address into `TRAFFIC_TILE_URL` in `js/config.js` (example inside the file). Check the provider's coverage for Bangladesh first.

## Emergency services (hospital / police / fire / fuel)
- Run `supabase/services.sql` once in the Supabase SQL Editor (already done for the current project). It creates the list and copies the starting services from `js/data.js`.
- Add, rename, re-icon, set a phone for, or delete a service: 🔒 Admin → **Services**. Pick the type and an icon, tap the map for the place, then Add.
- The public map does not show them all. Hospitals and police appear only when you are within 5 km of them (zoom does not matter); farther ones disappear, and the map follows you as you travel. Fire and fuel pins appear only when picked in the Nearby help panel. The Nearby help list is unchanged. To change the distance, edit `NEAR_KM` in `js/services.js`. If the database is unreachable, the last saved list (or `js/data.js`) is used.

## What the news job looks for
- Road accidents, highway robbery/hijack, **and street security incidents**: cocktail/crude-bomb blasts, vehicles set on fire, road blockades, clashes and vandalism.
- **English and Bangla.** Bangla headlines are matched on their own keywords.
- **Focus areas:** Dhaka (about 50 neighbourhoods such as Mirpur, Pallabi, Mohakhali, Badda, Rampura, Mohammadpur, Jatrabari, Tejgaon, Uttara), Sylhet, Brahmanbaria (Ashuganj, Sarail, Bhairab, Akhaura), Narsingdi, Gazipur and the highways between them. These places are looked up from a built-in list (`GAZETTEER_TEXT` in `news/fetch_news.py`), so they do not depend on the map search. To add a place, add one line there.
- One article naming several places (for example "buses burned in Pallabi, Badda and Rampura") becomes **one pending item per place**, up to 5, so each can be approved on its own.
- If an article says only "the capital" or "Dhaka", you get one pending item for the whole city with a large radius. Drag it to the right place when you review it.
- Search lists are in `news/feeds.txt`; add or remove lines there.
