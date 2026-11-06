"""
A small client for The Movie Database (TMDB). This product uses the TMDB API
but is not endorsed or certified by TMDB.

The read token lives in backend/.env as TMDB_TOKEN and never reaches the browser.
List calls are cached in memory for an hour so browsing the vault stays quick.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/"
_cache = {}
TTL = 60 * 60


class TMDBError(Exception):
    pass


def enabled():
    return bool(settings.TMDB_TOKEN)


def get(path, **params):
    if not enabled():
        raise TMDBError("TMDB is not configured (set TMDB_TOKEN in backend/.env).")
    params = {k: v for k, v in params.items() if v not in (None, "")}
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    hit = _cache.get(url)
    if hit and hit[0] > time.time():
        return hit[1]
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {settings.TMDB_TOKEN}", "accept": "application/json"})
    for attempt in range(3):  # TMDB occasionally drops a connection; try twice more
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(1 + attempt)
                continue
            raise TMDBError(f"TMDB returned {e.code}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise TMDBError("Couldn't reach TMDB") from e
    if len(_cache) > 2000:
        _cache.clear()
    _cache[url] = (time.time() + TTL, data)
    return data


def poster(path, size="w500"):
    return f"{IMG}{size}{path}" if path else None


def card(m):
    """A TMDB list result, trimmed to what a poster card needs."""
    return {
        "tmdb_id": m["id"],
        "title": m.get("title") or m.get("original_title") or "",
        "original_title": m.get("original_title") or "",
        "year": int(m["release_date"][:4]) if m.get("release_date") else None,
        "poster": poster(m.get("poster_path"), "w342"),
        "overview": m.get("overview") or "",
        "genre_ids": m.get("genre_ids") or [],
        "language": m.get("original_language") or "",
    }


def details(tmdb_id):
    """Everything we store on a Film, from one call."""
    m = get(f"/movie/{tmdb_id}", append_to_response="credits")
    directors = [c["name"] for c in m.get("credits", {}).get("crew", []) if c.get("job") == "Director"]
    return {
        "tmdb_id": m["id"],
        "title": m.get("title") or m.get("original_title") or "Untitled",
        "original_title": m.get("original_title") if m.get("original_title") != m.get("title") else "",
        "year": int(m["release_date"][:4]) if m.get("release_date") else None,
        "director": ", ".join(directors[:2]),
        "country": " / ".join(c["name"] for c in m.get("production_countries", [])[:2]),
        "language": next((l.get("english_name") for l in m.get("spoken_languages", []) if l.get("iso_639_1") == m.get("original_language")), ""),
        "runtime": m.get("runtime") or None,
        "genres": ", ".join(g["name"] for g in m.get("genres", [])),
        "tagline": (m.get("tagline") or "")[:200],
        "synopsis": m.get("overview") or "",
        "poster_url": poster(m.get("poster_path")) or "",
    }
