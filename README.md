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

## Production notes

- Set the variables in `.env.example` (secret key, `DJANGO_DEBUG=0`, hosts, CORS origins) and move to Postgres.
- Run `collectstatic`, and serve `media/` from the web server or object storage.
- Build the frontend with `npm run build`, and set `VITE_API_URL` if the API lives on a different origin.
