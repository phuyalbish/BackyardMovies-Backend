# Backyard Movies: backend

Website for [@backyardmoviesnepal](https://www.instagram.com/backyardmoviesnepal): free open-air film nights in a Kirtipur garden, plus a members' community.

Django 6 + Django REST Framework, JWT auth, SQLite in development, film data from TMDB.

## Run it

Frontend: [BackyardMovies-Frontend](https://github.com/phuyalbish/BackyardMovies-Frontend). This repo is the Django API and the admin (the "Projection Booth").

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # then set TMDB_TOKEN; for local work also set DJANGO_DEBUG=1 and DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed          # 26 films + Night One (Lion, 6 Nov 2026)
.venv/bin/python manage.py seed --demo   # optional: 5 sample members, votes, comments
.venv/bin/python manage.py tmdb_sync     # real posters and details from TMDB
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver 8000
```

The CMS is the **Projection Booth**, a page of the frontend at `/booth`; this repo serves its staff API under `/api/booth/`. Django's admin at `/booth/` here is a fallback.

Demo accounts created by `seed --demo` all use the password `backyard-demo-1` (`aarati`, `bibek`, `sushma`, `rohan`, `pema`). To start clean before going live, delete `db.sqlite3`, then run `migrate` and `seed` without `--demo`.

## Deploy on cPanel

Deploys run from GitHub: Actions > "Deploy backend to cPanel" > Run workflow. It uploads the code over SSH to the app folder, then runs `deploy.sh` (Python check, `pip install`, `migrate`, `collectstatic`, restart) and checks that `/api/site/` answers.

**Once, in cPanel:**
1. Domains: create the API subdomain (e.g. `backyardapi.hellotrekkers.com`) and make sure it has an SSL certificate.
2. Setup Python App > Create: Python **3.12 or newer**, application root `backyardapi`, application URL the subdomain, startup file `passenger_wsgi.py`, entry point `application`.
3. SSH Access > Manage SSH Keys: import or generate a key pair for deploys and **Authorize** it.

**Repository secrets** (Settings > Secrets and variables > Actions): `SSH_PRIVATE_KEY`, `SSH_USERNAME`, `SERVER_IP`, and `TMDB_TOKEN` (the TMDB read access token; each deploy writes it into the server's `.env`). The app folder (`backyardapi`) and API address are set at the top of `.github/workflows/deploy.yml`.

**`.env` on the server.** You don't need to write it. Each deploy fills in whatever is missing in `~/backyardapi/.env`: a random `DJANGO_SECRET_KEY` (generated once, then kept), `DJANGO_DEBUG=0`, the allowed host and trusted origin from `API_URL`, `CORS_ORIGINS` from `SITE_URL` (both set at the top of the workflow), `SERVE_MEDIA=1`, and `TMDB_TOKEN` from the secret. A line you set by hand is never changed.

**After the first deploy**, in cPanel Terminal:
```bash
source ~/virtualenv/backyardapi/*/bin/activate && cd ~/backyardapi
python manage.py migrate          # if the first deploy didn't get this far
python manage.py seed             # 26 films + Night One (Lion)
python manage.py tmdb_sync        # real posters and details
python manage.py createsuperuser  # your login for the booth
```

The database (`db.sqlite3`) and uploads (`media/`) live only on the server and deploys never touch them. Back them up with cPanel > Backup.

## What's on the site

| Page | Route | What it does |
| --- | --- | --- |
| Home | `/` | Night-garden hero with the next film on a bedsheet screen, a countdown, a film-strip marquee, the next night, and a wall of past nights once there are some |
| Programme | `/screenings` | Upcoming nights and the archive of past ones |
| Screening | `/screenings/:id` | Ticket stub, seat meter, reserve 1 to 4 free seats, who's coming, pre-show chat |
| Vault | `/films` | Every film on TMDB, from every country and decade, with real posters: search, genre, decade, country and sort |
| Film | `/films/:slug` | Vote to screen it, log it in your diary with a rating |
| Ballot | `/ballot` | Members only. The films the hosts put on the ballot, ranked by votes |
| Member | `/u/:username` | Profile and diary of watched films |
| Account | `/me` | Profile card (edit in place, sign out), tickets, and your private watchlist, watched and favourites; staff also get a link to the Projection Booth |

## The film catalogue (TMDB)

The Vault searches and browses [The Movie Database](https://www.themoviedb.org/). Put a free read access token in `.env` as `TMDB_TOKEN` (themoviedb.org, Settings, API). Opening a TMDB film, or marking it, saves it as a local film with its poster, director, country, runtime and synopsis, so votes, screenings, watchlists and diaries all work on it. `python manage.py tmdb_sync` links films added by hand to TMDB and fills in what is missing; `--all` refreshes every film (an uploaded poster is never replaced).

TMDB is free for non-commercial use with the credit shown in the footer. If the site ever charges or runs ads, that needs a separate agreement with TMDB.

## Posters

Films with neither an uploaded poster nor a TMDB poster get a generated, screen-printed poster in one of six layouts (sun disc, stacked wood type, diagonal split, Swiss grid, spiral, Polish stripes). The film's `palette` field (two or three hex colours) sets the colours. Uploading a poster image or pasting a poster URL in the booth replaces it.

## Running a night from the booth

The booth is at **`/booth`** on the site (for example `https://backyard.hellotrekkers.com/booth`). Sign in with a staff account; anyone else sees "Staff only". It has six sections:

1. **Tonight**: the next night at a glance. Seats booked, who's coming (tick them in as they arrive), the ballot leaders and the latest comments. **Mark screened** closes the night and writes a diary entry for everyone ticked in.
2. **Films**: the search finds our films and every film on TMDB; a TMDB film is added the moment you switch it on or open it. **On ballot** lets members vote for a film; **Film strip** puts its poster in the strip that rolls across the home page. The menu on each row fills details in from TMDB, resets votes for a new round, or deletes. **Edit** opens the film's own page with every field, including a poster upload.
3. **Screenings**: plan a night (film, time, venue, seats, host note), feature it on the home page, and open it (its own page) to edit it, see bookings and tick people in. Cancel or mark screened from there or from the row menu.
4. **Comments**: hide a comment without deleting it, or delete it.
5. **Members**: everyone with an account; give or remove staff access.
6. **Settings**: an image or short video (up to 60 MB) for the bedsheet screen at the top of the home page, and the venue, address, WhatsApp, phone and Instagram shown in the footer.

Django's own admin still exists at `/booth/` on the API address, as a fallback for things the booth doesn't do (passwords, superusers). It is trimmed to films, screenings, reservations, comments and site settings.
