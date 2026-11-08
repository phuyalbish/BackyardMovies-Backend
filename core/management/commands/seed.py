"""Seed the vault and the first night.

    python manage.py seed           # films, site settings, the Lion screening
    python manage.py seed --demo    # also sample members, votes and comments
"""
import random
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from core.models import Comment, Film, LogEntry, Reservation, Screening, Shelf, SiteSettings, Vote

FILMS = [
    # title, year, director, country, runtime, genres, palette, tagline, synopsis
    ("Lion", 2016, "Garth Davis", "Australia / India", 118, "Drama, Biography", "#f4b7b4,#d8324a,#fff4e6",
     "Twenty-five years. One train. A map on a laptop.",
     "A five-year-old boy falls asleep on a train in Khandwa and wakes up a thousand miles from home. "
     "Adopted by a couple in Tasmania, he grows up loved and unsettled, until satellite images and memory start pulling him back."),
    ("Seven Samurai", 1954, "Akira Kurosawa", "Japan", 207, "Action, Drama", "#e9e1cc,#16130f,#b3261e",
     "Seven swords for a village that cannot pay.",
     "Farmers expecting bandits after the harvest hire a handful of masterless samurai for nothing but rice. "
     "The rain, the mud and the final battle remain the template for every ensemble action film since."),
    ("Rashomon", 1950, "Akira Kurosawa", "Japan", 88, "Crime, Drama", "#d9cfb8,#1d1a17,#7a8c5a",
     "Four witnesses. One forest. No truth.",
     "Under a ruined gate in the rain, three men retell a killing in the woods. Every account contradicts the last."),
    ("Pather Panchali", 1955, "Satyajit Ray", "India", 125, "Drama", "#efe4c8,#2b2a26,#c98b2b",
     "A boy, a sister, a train across the kaash flowers.",
     "Apu grows up in a crumbling Bengal village with his restless father, his worn-out mother and his sister Durga. "
     "Ray's debut and still one of the gentlest, most devastating films ever made."),
    ("Kalo Pothi", 2015, "Min Bahadur Bham", "Nepal", 90, "Drama", "#e7dcc3,#111111,#c43b2a",
     "Two boys. One hen. A country at war.",
     "In a hill village during the civil war, Prakash and his friend Kiran go looking for a black hen that was sold away. "
     "Nepal's first film at Venice, and a quiet miracle of a debut."),
    ("Cinema Paradiso", 1988, "Giuseppe Tornatore", "Italy", 155, "Drama, Romance", "#f1d9a6,#3a1f1a,#d6643a",
     "Every projectionist keeps a reel of what was cut.",
     "A famous director returns to the Sicilian village where a projectionist named Alfredo taught him to love the movies."),
    ("In the Mood for Love", 2000, "Wong Kar-wai", "Hong Kong", 98, "Romance, Drama", "#8f1d21,#efd9b4,#1b1414",
     "Neighbours. Noodles. Nothing said out loud.",
     "Two people in 1962 Hong Kong discover their spouses are having an affair, and slowly, carefully, refuse to have one of their own."),
    ("Spirited Away", 2001, "Hayao Miyazaki", "Japan", 125, "Animation, Fantasy", "#c94a3a,#f3e2b8,#2d5d6b",
     "Do not forget your name.",
     "Ten-year-old Chihiro wanders into a bathhouse for spirits, where her parents have been turned into pigs and her name is the first thing they take."),
    ("2001: A Space Odyssey", 1968, "Stanley Kubrick", "United Kingdom / USA", 149, "Sci-Fi", "#0a0a0a,#f2f2f2,#d8341f",
     "From bone to starchild in one cut.",
     "A black monolith appears at the dawn of man, again on the moon, and again near Jupiter, where a calm computer has its own plans."),
    ("The Godfather", 1972, "Francis Ford Coppola", "USA", 175, "Crime, Drama", "#0f0d0b,#e9dfc8,#8a1a14",
     "The family business is the family.",
     "The ageing patriarch of a New York crime family hands the empire to his youngest son, the one who wanted nothing to do with it."),
    ("Bicycle Thieves", 1948, "Vittorio De Sica", "Italy", 89, "Drama", "#e8e3d6,#1e1e1e,#9c8a6a",
     "Without the bicycle, there is no job.",
     "In postwar Rome a poster-hanger's bicycle is stolen on his first day of work. He and his son search the whole city for it."),
    ("Casablanca", 1942, "Michael Curtiz", "USA", 102, "Romance, Drama", "#f0e6cf,#1f2a2e,#b8862f",
     "Of all the gin joints in all the towns.",
     "A cynical American runs a nightclub in wartime Morocco until the woman who left him walks in with her husband, needing his help."),
    ("Parasite", 2019, "Bong Joon-ho", "South Korea", 132, "Thriller, Drama", "#2f3b2a,#efe9dc,#c1a14a",
     "Everyone has a plan. Until the basement.",
     "A family living in a semi-basement cons its way, one job at a time, into the household of a rich family on the hill."),
    ("Taxi Driver", 1976, "Martin Scorsese", "USA", 114, "Crime, Drama", "#f4c430,#121212,#c22a1d",
     "Night shifts. Every borough. No sleep.",
     "Travis Bickle, a Vietnam veteran who cannot sleep, drives a cab through 1970s New York and decides to clean it up himself."),
    ("Amélie", 2001, "Jean-Pierre Jeunet", "France", 122, "Comedy, Romance", "#2f6b3a,#d7322b,#f2d6a2",
     "She fixes everyone's life except her own.",
     "A shy waitress in Montmartre starts secretly arranging small joys for strangers, then has to find the nerve to arrange one for herself."),
    ("Pulp Fiction", 1994, "Quentin Tarantino", "USA", 154, "Crime", "#f1c232,#141414,#c0392b",
     "Hitmen, a boxer, a briefcase and a very long breakfast.",
     "Interlocking stories of Los Angeles criminals, told out of order and talked through at length."),
    ("Chungking Express", 1994, "Wong Kar-wai", "Hong Kong", 102, "Romance, Comedy", "#f6d54a,#1f6f8b,#e04b2a",
     "California Dreamin', on repeat.",
     "Two lovesick Hong Kong cops, one canned pineapple expiry date, and a snack-bar girl who lets herself into an apartment."),
    ("Vertigo", 1958, "Alfred Hitchcock", "USA", 128, "Thriller, Mystery", "#d9442b,#151515,#f2e7d3",
     "He fell for her twice.",
     "A retired detective with a fear of heights is hired to follow a friend's wife through San Francisco, and becomes obsessed."),
    ("Pashupati Prasad", 2016, "Dipendra K. Khanal", "Nepal", 120, "Drama, Comedy", "#e9a23b,#3b1f14,#f4ead6",
     "From the ghats of Pashupati to the streets of Kathmandu.",
     "A young man who survives by collecting coins at Pashupatinath leaves for the city, and finds Kathmandu less holy than advertised."),
    ("The Seventh Seal", 1957, "Ingmar Bergman", "Sweden", 96, "Drama, Fantasy", "#ece8df,#121212,#6e6e6e",
     "A knight, a chessboard, and Death across the table.",
     "Returning from the Crusades to a plague-struck Sweden, a knight challenges Death to chess to buy time for one good act."),
    ("Tokyo Story", 1953, "Yasujiro Ozu", "Japan", 136, "Drama", "#efe7d2,#2c3a4a,#b84a33",
     "The children are busy.",
     "An elderly couple travels to Tokyo to visit their grown children, who have very little time for them."),
    ("Stalker", 1979, "Andrei Tarkovsky", "USSR", 162, "Sci-Fi, Drama", "#5f6b3c,#1b1d17,#c9b78a",
     "Somewhere in the Zone, a room grants wishes.",
     "A guide leads a writer and a scientist through a forbidden wasteland toward a room said to give you what you truly want."),
    ("City of God", 2002, "Fernando Meirelles", "Brazil", 130, "Crime, Drama", "#f2a541,#1a120c,#c8321f",
     "Fight and you'll never survive. Run and you'll never escape.",
     "Rocket wants to be a photographer. Li'l Zé wants to run the favela. Both grew up in the same streets of Rio."),
    ("Before Sunrise", 1995, "Richard Linklater", "USA / Austria", 101, "Romance", "#f0c9a6,#22324a,#e86f4c",
     "One train. One night. Vienna.",
     "An American and a French student meet on a train and step off together in Vienna, with only until morning."),
    ("Children of Heaven", 1997, "Majid Majidi", "Iran", 89, "Family, Drama", "#f2e3c2,#2a5c7a,#d9632b",
     "One pair of shoes, two schoolchildren.",
     "Ali loses his little sister's only shoes. Rather than tell their parents, they share his sneakers and race between school shifts."),
    ("Sholay", 1975, "Ramesh Sippy", "India", 204, "Action, Adventure", "#e8a53a,#3a1a10,#f2e2c2",
     "Two small-time crooks. One retired policeman. Gabbar.",
     "A former police officer hires two charming outlaws to capture the bandit who destroyed his family."),
]

# The first round of voting. Change it any time in the booth (Films, "On the ballot").
FIRST_BALLOT = ["Spirited Away", "Seven Samurai", "Kalo Pothi", "Cinema Paradiso", "Children of Heaven", "Chungking Express"]

DEMO_PEOPLE = [
    ("aarati", "Aarati Shrestha", "Patan", "In the Mood for Love", "Collects ticket stubs. Cries at train scenes."),
    ("bibek", "Bibek Maharjan", "Kirtipur", "Seven Samurai", "Projector wrangler. Will fix your HDMI cable."),
    ("sushma", "Sushma Gurung", "Pokhara", "Spirited Away", "Animation person. Strong opinions about Ghibli food."),
    ("rohan", "Rohan Karki", "Baneshwor", "Taxi Driver", "Writes three-line reviews and refuses to elaborate."),
    ("pema", "Pema Lama", "Boudha", "Stalker", "Slow cinema, slower tea."),
]

DEMO_TALK = [
    ("Lion", "aarati", "Bring tissues. The last ten minutes of this one wreck me every time."),
    ("Lion", "bibek", "Testing the projector tonight. The sheet is tighter than last week, promise."),
    ("Kalo Pothi", "pema", "Can we please screen this next? Watched it at a festival and nobody I know has seen it."),
    ("Seven Samurai", "rohan", "Three and a half hours. Under the stars. With an interval for momos. Yes."),
    ("Spirited Away", "sushma", "The train scene on a bedsheet screen would be unreal."),
]


class Command(BaseCommand):
    help = "Seed films, site settings and the first screening. --demo adds sample members and activity."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true")

    def attach_posters(self, films):
        """Use art from the repo's posters/ folder (posters/<slug>.png or .jpg) for films that have none."""
        from PIL import Image
        folder = Path(settings.BASE_DIR).parent / "posters"
        for f in films.values():
            if f.poster:
                continue
            names = (f.slug, slugify(f.title))
            src = next((folder / f"{n}.{ext}" for n in names for ext in ("png", "jpg", "jpeg", "webp")
                        if (folder / f"{n}.{ext}").exists()), None)
            if not src:
                continue
            img = Image.open(src).convert("RGB")
            img.thumbnail((900, 1400))
            buf = BytesIO()
            img.save(buf, "JPEG", quality=84, optimize=True, progressive=True)
            f.poster.save(f"{f.slug}.jpg", ContentFile(buf.getvalue()), save=True)
            self.stdout.write(f"Poster attached: {f.title}")

    def handle(self, *args, demo=False, **opts):
        SiteSettings.load()
        films = {}
        for title, year, director, country, runtime, genres, palette, tagline, synopsis in FILMS:
            f, created = Film.objects.update_or_create(
                title=title, year=year,
                defaults=dict(director=director, country=country, runtime=runtime, genres=genres,
                              palette=palette, tagline=tagline, synopsis=synopsis, status="vault"),
            )
            if created:  # a fresh database starts with these on our list and in the home page strip
                f.listed = f.in_strip = True
                f.save(update_fields=["listed", "in_strip"])
            films[title] = f
        self.stdout.write(f"{len(films)} films in the vault")
        self.attach_posters(films)
        if not Film.objects.filter(on_ballot=True).exists():
            Film.objects.filter(title__in=FIRST_BALLOT).update(on_ballot=True)
            self.stdout.write(f"{len(FIRST_BALLOT)} films put on the ballot")

        tz = timezone.get_current_timezone()
        start = datetime(2026, 11, 6, 18, 0, tzinfo=tz)
        lion, _ = Screening.objects.update_or_create(
            film=films["Lion"], starts_at=start,
            defaults=dict(
                title="Night One", ends_at=start + timedelta(hours=3, minutes=30),
                venue="Kirtipur Comfort Homestay's backyard", address="Kirtipur, Kathmandu",
                capacity=30, entry="Free", is_featured=True, status="upcoming",
                host_note=("Our first ever movie night. Gates open at six, the film rolls once it is dark enough. "
                           "Bring a shawl, the garden gets cold after eight. Reservations on WhatsApp "
                           "977-9709707037 or right here."),
            ),
        )
        self.stdout.write(f"Screening: {lion}")

        if not demo:
            return

        User = get_user_model()
        people = []
        for username, name, city, fav, bio in DEMO_PEOPLE:
            u, created = User.objects.get_or_create(username=username, defaults={"email": f"{username}@example.com"})
            if created:
                u.set_password("backyard-demo-1")
                u.save()
            p = u.profile
            p.display_name, p.city, p.favourite_film, p.bio = name, city, fav, bio
            p.save()
            people.append(u)

        rng = random.Random(6)
        for u in people:
            for f in rng.sample([films[t] for t in FIRST_BALLOT if t in films], 3):
                Vote.objects.get_or_create(user=u, film=f)
            for f in rng.sample(list(films.values()), 4):
                LogEntry.objects.get_or_create(user=u, film=f, defaults={"rating": rng.randint(3, 5),
                                                                         "watched_on": timezone.localdate() - timedelta(days=rng.randint(3, 300))})
                Shelf.objects.update_or_create(user=u, film=f, defaults={"watched": True})
        for u in people[:4]:
            Reservation.objects.get_or_create(screening=lion, user=u,
                                              defaults={"guests": rng.choice([[], [], ["Sujan Tamang"], ["Mira Rai"]])})

        by_name = {u.username: u for u in people}
        for title, who, body in DEMO_TALK:
            target = {"screening": lion} if title == "Lion" else {"film": films[title]}
            Comment.objects.get_or_create(user=by_name[who], body=body, **target)
        self.stdout.write(self.style.SUCCESS("Demo members, votes and comments added"))
