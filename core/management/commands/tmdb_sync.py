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
                tid = f.tmdb_id or tmdb.match([f.title, f.original_title], f.year)
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
            f.apply_tmdb({**d, "tmdb_id": tid})
            linked += 1
            self.stdout.write(f"  {f.title} ({f.year}) -> TMDB {tid}")
        self.stdout.write(self.style.SUCCESS(f"Linked {linked} film(s), {missed} without a match."))
