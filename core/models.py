from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.text import slugify

User = settings.AUTH_USER_MODEL


def unique_slug(instance, value, field="slug"):
    base = slugify(value)[:60] or "item"
    slug, n = base, 2
    Model = type(instance)
    while Model.objects.filter(**{field: slug}).exclude(pk=instance.pk).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


class SiteSettings(models.Model):
    """Single row of editable site copy. Edit it in the admin."""

    tagline = models.CharField(max_length=160, default="A backyard, a bedsheet screen, and a city full of film people.")
    hero_quote = models.CharField(max_length=240, default="Cinema is a mirror by which we often see ourselves.")
    hero_quote_author = models.CharField(max_length=80, default="Akira Kurosawa")
    instagram = models.CharField(max_length=80, default="backyardmoviesnepal")
    whatsapp = models.CharField(max_length=40, default="977-9709707037")
    phone = models.CharField(max_length=40, default="977-9849828857")
    venue_name = models.CharField(max_length=120, default="Kirtipur Comfort Homestay")
    venue_address = models.CharField(max_length=200, default="Kirtipur, Kathmandu")
    about = models.TextField(
        default=(
            "Backyard Movies started with one projector, a stretched white sheet and a garden "
            "in Kirtipur. We screen films we love, under the sky, for anyone who wants to sit "
            "with strangers and leave as friends. Entry is free. Bring a blanket."
        )
    )

    class Meta:
        verbose_name = "Site settings"
        verbose_name_plural = "Site settings"

    def __str__(self):
        return "Site settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=80, blank=True)
    bio = models.CharField(max_length=280, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    favourite_film = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=80, blank=True)
    favourites_public = models.BooleanField(default=False, help_text="Show this member's favourite films on their public profile")

    def __str__(self):
        return self.display_name or self.user.username


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def make_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance, defaults={"display_name": instance.username})


class Film(models.Model):
    class Status(models.TextChoices):
        VAULT = "vault", "In the vault"
        SUGGESTED = "suggested", "Suggested (awaiting review)"
        REJECTED = "rejected", "Not this time"

    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=80, unique=True, blank=True)
    original_title = models.CharField(max_length=160, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)
    director = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=80, blank=True)
    language = models.CharField(max_length=60, blank=True)
    runtime = models.PositiveIntegerField(null=True, blank=True, help_text="Minutes")
    genres = models.CharField(max_length=160, blank=True, help_text="Comma separated, e.g. Drama, Crime")
    tagline = models.CharField(max_length=200, blank=True)
    synopsis = models.TextField(blank=True)
    poster = models.ImageField(upload_to="posters/", blank=True, null=True)
    poster_url = models.URLField(blank=True, help_text="Used when no poster file is uploaded")
    trailer_url = models.URLField(blank=True)
    palette = models.CharField(
        max_length=60, blank=True,
        help_text="Optional: two or three hex colours for the generated poster, e.g. #e8572a,#0d1424",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.VAULT)
    tmdb_id = models.PositiveIntegerField(null=True, blank=True, unique=True, help_text="The Movie Database id, filled in automatically")
    on_ballot = models.BooleanField(default=False, help_text="Show this film on the members' ballot. Only ballot films can be voted for.")
    suggested_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="suggestions")
    pitch = models.TextField(blank=True, help_text="Why the suggester wants it screened")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return f"{self.title} ({self.year})" if self.year else self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, f"{self.title} {self.year or ''}")
        super().save(*args, **kwargs)

    def apply_tmdb(self, d, overwrite=False):
        """Fill this film from tmdb.details(). An uploaded poster always wins; other fields only
        replace empty ones unless overwrite=True. Saves."""
        self.tmdb_id = d.get("tmdb_id") or self.tmdb_id
        for k, v in d.items():
            if k == "tmdb_id" or not v:
                continue
            if k == "poster_url":
                if not self.poster:
                    self.poster_url = v
            elif overwrite or not getattr(self, k, None):
                setattr(self, k, v)
        self.save()

    @property
    def genre_list(self):
        return [g.strip() for g in self.genres.split(",") if g.strip()]


class Screening(models.Model):
    class Status(models.TextChoices):
        UPCOMING = "upcoming", "Upcoming"
        DONE = "done", "Screened"
        CANCELLED = "cancelled", "Cancelled"

    film = models.ForeignKey(Film, on_delete=models.PROTECT, related_name="screenings")
    title = models.CharField(max_length=160, blank=True, help_text="Optional event name, e.g. 'Night One'")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    venue = models.CharField(max_length=160, default="Kirtipur Comfort Homestay's backyard")
    address = models.CharField(max_length=200, blank=True, default="Kirtipur, Kathmandu")
    capacity = models.PositiveIntegerField(default=30)
    entry = models.CharField(max_length=60, default="Free")
    host_note = models.TextField(blank=True, help_text="A few words from the host shown on the screening page")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UPCOMING)
    is_featured = models.BooleanField(default=False, help_text="Pin to the home page hero")

    class Meta:
        ordering = ["starts_at"]

    def __str__(self):
        return f"{self.film.title} on {timezone.localtime(self.starts_at):%d %b %Y}"

    @property
    def seats_taken(self):
        return self.reservations.aggregate(s=models.Sum("seats"))["s"] or 0

    @classmethod
    def next_up(cls):
        """The night the site is pointing people at: featured first, then the soonest."""
        return (cls.objects.filter(status=cls.Status.UPCOMING, starts_at__gte=timezone.now() - timezone.timedelta(hours=4))
                .order_by("-is_featured", "starts_at").select_related("film").first())

    def mark_screened(self):
        """Close the night: status done, and a diary entry plus a 'watched' mark for everyone
        marked attended. Safe to run twice. Returns how many diary entries were written."""
        made = 0
        with transaction.atomic():
            self.status = self.Status.DONE
            self.save()
            for r in self.reservations.filter(attended=True).select_related("user"):
                _, created = LogEntry.objects.get_or_create(
                    user=r.user, film=self.film, screening=self,
                    defaults={"watched_on": timezone.localtime(self.starts_at).date(), "watched_with": "Backyard Movies"},
                )
                Shelf.objects.update_or_create(user=r.user, film=self.film, defaults={"watched": True, "watchlist": False})
                made += created
        return made

    @property
    def seats_left(self):
        return max(self.capacity - self.seats_taken, 0)


class Reservation(models.Model):
    screening = models.ForeignKey(Screening, on_delete=models.CASCADE, related_name="reservations")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reservations")
    seats = models.PositiveSmallIntegerField(default=1)
    note = models.CharField(max_length=200, blank=True)
    attended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("screening", "user")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} x{self.seats} for {self.screening}"

    @property
    def code(self):
        return f"BYM-{self.screening_id:03d}-{self.pk:04d}"


class Vote(models.Model):
    """A member's vote for what the backyard should screen next."""

    film = models.ForeignKey(Film, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="votes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("film", "user")


class Shelf(models.Model):
    """A member's private marks on a film: on their watchlist, watched, favourite. Only they see it."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="shelf")
    film = models.ForeignKey(Film, on_delete=models.CASCADE, related_name="shelved")
    watchlist = models.BooleanField(default=False)
    watched = models.BooleanField(default=False)
    favourite = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    MARKS = ("watchlist", "watched", "favourite")

    class Meta:
        unique_together = ("user", "film")
        ordering = ["-updated_at"]

    def __str__(self):
        marks = ", ".join(m for m in self.MARKS if getattr(self, m)) or "nothing"
        return f"{self.user} / {self.film}: {marks}"


class LogEntry(models.Model):
    """A film a member has watched, optionally at one of our screenings."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="log")
    film = models.ForeignKey(Film, on_delete=models.CASCADE, related_name="log_entries")
    screening = models.ForeignKey(Screening, null=True, blank=True, on_delete=models.SET_NULL, related_name="log_entries")
    rating = models.PositiveSmallIntegerField(null=True, blank=True, help_text="1 to 5")
    note = models.TextField(blank=True)
    watched_on = models.DateField(default=timezone.localdate)
    watched_with = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-watched_on", "-created_at"]
        verbose_name_plural = "Log entries"

    def __str__(self):
        return f"{self.user} watched {self.film}"


class Comment(models.Model):
    """One comment model for films and screenings. Exactly one target is set."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="comments")
    film = models.ForeignKey(Film, null=True, blank=True, on_delete=models.CASCADE, related_name="comments")
    screening = models.ForeignKey(Screening, null=True, blank=True, on_delete=models.CASCADE, related_name="comments")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    body = models.TextField(max_length=2000)
    is_hidden = models.BooleanField(default=False, help_text="Hide from the site without deleting")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user}: {self.body[:40]}"
