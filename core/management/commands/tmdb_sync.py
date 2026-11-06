"""
Link films to The Movie Database and fill in what's missing (poster, director, runtime...).

    python manage.py tmdb_sync          # films without a TMDB id
    python manage.py tmdb_sync --all    # refresh every film (never overwrites an uploaded poster or text you typed)
"""
from django.core.management.base import BaseCommand

from core import tmdb
from core.models import Film


class Command(BaseCommand):
    help = "Match films to TMDB and fill in posters and details"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Also refresh films that already have a TMDB id")

    def handle(self, *args, **opts):
        if not tmdb.enabled():
            self.stdout.write(self.style.WARNING("TMDB_TOKEN is not set in backend/.env, skipping."))
            return
        qs = Film.objects.all() if opts["all"] else Film.objects.filter(tmdb_id__isnull=True)
        linked = missed = 0
        for f in qs:
            try:
                tid = f.tmdb_id or self.match(f)
                if not tid:
                    missed += 1
                    self.stdout.write(f"  no match: {f.title} ({f.year})")
                    continue
                if Film.objects.filter(tmdb_id=tid).exclude(pk=f.pk).exists():
                    self.stdout.write(f"  skipped (another film already has TMDB {tid}): {f.title}")
                    continue
                d = tmdb.details(tid)
            except tmdb.TMDBError as e:
                self.stdout.write(self.style.ERROR(f"  {f.title}: {e}"))
                continue
            f.tmdb_id = tid
            for k, v in d.items():
                if k == "poster_url":
                    if v and not f.poster:  # an uploaded poster always wins
                        f.poster_url = v
                elif v and not getattr(f, k, None):
                    setattr(f, k, v)
            f.save()
            linked += 1
            self.stdout.write(f"  {f.title} ({f.year}) -> TMDB {tid}")
        self.stdout.write(self.style.SUCCESS(f"Linked {linked} film(s), {missed} without a match."))

    def match(self, f):
        """Best TMDB id for a film: same original release year, exact title first."""
        def search(q, **kw):
            return tmdb.get("/search/movie", query=q, **kw).get("results", [])

        def year_of(r):
            d = r.get("release_date") or ""
            return int(d[:4]) if d[:4].isdigit() else None

        titles = [t for t in (f.title, f.original_title) if t]
        res = []
        for t in titles:
            res = search(t, primary_release_year=f.year or "")
            if res:
                break
        if not res:  # release year differs by one in some databases
            res = [r for t in titles for r in search(t) if f.year and year_of(r) and abs(year_of(r) - f.year) <= 1]
        if not res:
            return None
        names = {t.casefold() for t in titles}
        exact = [r for r in res if {(r.get("title") or "").casefold(), (r.get("original_title") or "").casefold()} & names]
        return (exact or res)[0]["id"]
