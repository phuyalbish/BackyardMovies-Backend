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

The admin is the **Projection Booth** at `http://127.0.0.1:8000/booth/`.

Demo accounts created by `seed --demo` all use the password `backyard-demo-1` (`aarati`, `bibek`, `sushma`, `rohan`, `pema`). To start clean before going live, delete `db.sqlite3`, then run `migrate` and `seed` without `--demo`.

## Deploy on cPanel

Deploys run from GitHub: Actions > "Deploy backend to cPanel" > Run workflow. It uploads the code over SSH to the app folder, writes `.env` from the repository secrets, then runs `deploy.sh` (Python check, `pip install`, `migrate`, `collectstatic`, restart) and checks that `/api/site/` answers.

**Once, in cPanel:**
1. Domains: create the API subdomain (e.g. `backyardapi.hellotrekkers.com`) and make sure it has an SSL certificate.
2. Setup Python App > Create: Python **3.12 or newer**, application root `backyardapi`, application URL the subdomain, startup file `passenger_wsgi.py`, entry point `application`.
3. SSH Access > Manage SSH Keys: import or generate a key pair for deploys and **Authorize** it.

**Repository secrets** (Settings > Secrets and variables > Actions):

| Secret | Example |
| --- | --- |
| `SSH_PRIVATE_KEY` | the private half of the key authorized in cPanel |
| `SSH_USERNAME` | your cPanel username |
| `SERVER_IP` | the server's IP or hostname |
| `SSH_PORT` | optional, defaults to 22 |
| `APP_DIR` | optional, defaults to `backyardapi` |
| `API_DOMAIN` | `backyardapi.hellotrekkers.com` |
| `SITE_ORIGINS` | the website's address(es), e.g. `https://backyard.hellotrekkers.com` |
| `DJANGO_SECRET_KEY` | a long random string |
| `TMDB_TOKEN` | the TMDB read access token |

**After the first deploy**, in cPanel Terminal:
```bash
source ~/virtualenv/backyardapi/*/bin/activate && cd ~/backyardapi
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
| Account | `/me` | Profile card (edit in place, sign out), tickets, and your private watchlist, watched and favourites; staff also get a link to the booth |

## The film catalogue (TMDB)

The Vault searches and browses [The Movie Database](https://www.themoviedb.org/). Put a free read access token in `.env` as `TMDB_TOKEN` (themoviedb.org, Settings, API). Opening a TMDB film, or marking it, saves it as a local film with its poster, director, country, runtime and synopsis, so votes, screenings, watchlists and diaries all work on it. `python manage.py tmdb_sync` links films added by hand to TMDB and fills in what is missing; `--all` refreshes every film (an uploaded poster is never replaced).

TMDB is free for non-commercial use with the credit shown in the footer. If the site ever charges or runs ads, that needs a separate agreement with TMDB.

## Posters

Films with neither an uploaded poster nor a TMDB poster get a generated, screen-printed poster in one of six layouts (sun disc, stacked wood type, diagonal split, Swiss grid, spiral, Polish stripes). The film's `palette` field (two or three hex colours) sets the colours. Uploading a poster image or pasting a poster URL in the booth replaces it.

## Running a night from the booth

1. **Films**: add films, or approve member suggestions with the "Move to the vault" action.
2. **Ballot**: tick *On the ballot* on the films members should choose between (or select them and run "Put on the ballot"). Only those films appear on the ballot and only they can be voted for. "Reset votes" clears a round.
3. **Screenings**: create the night and tick *featured* to put it on the home page hero. Reservations appear inline.
4. On the night, tick *attended* on reservations. Then run **Mark as screened**, which writes a diary entry for everyone marked attended.
5. **Comments**: tick *hidden* to take a comment down without deleting it.
6. **Site settings**: edit the venue, WhatsApp, phone and Instagram handle.
