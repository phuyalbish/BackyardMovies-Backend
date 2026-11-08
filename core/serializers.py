from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Comment, Film, LogEntry, Profile, Reservation, Screening, SiteSettings, Vote

User = get_user_model()


def media_url(request, field):
    if not field:
        return None
    url = field.url
    return request.build_absolute_uri(url) if request else url


class SiteSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteSettings
        exclude = ["id"]


class MemberSerializer(serializers.ModelSerializer):
    """Small public profile for a member."""

    display_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "display_name", "avatar"]

    def get_display_name(self, u):
        p = getattr(u, "profile", None)
        return (p and p.display_name) or u.username

    def get_avatar(self, u):
        p = getattr(u, "profile", None)
        return media_url(self.context.get("request"), p.avatar) if p else None


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ["display_name", "bio", "avatar", "favourite_film", "city", "favourites_public"]


class MeSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer()

    class Meta:
        model = User
        fields = ["id", "username", "email", "is_staff", "profile", "date_joined"]
        read_only_fields = ["id", "username", "is_staff", "date_joined"]

    def update(self, instance, data):
        profile_data = data.pop("profile", {})
        instance.email = data.get("email", instance.email)
        instance.save()
        for k, v in profile_data.items():
            setattr(instance.profile, k, v)
        instance.profile.save()
        return instance


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    display_name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ["username", "email", "password", "display_name"]

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, data):
        display_name = data.pop("display_name", "")
        user = User.objects.create_user(**data)
        if display_name:
            user.profile.display_name = display_name
            user.profile.save()
        return user


class FilmCardSerializer(serializers.ModelSerializer):
    poster = serializers.SerializerMethodField()
    genres = serializers.SerializerMethodField()
    votes = serializers.IntegerField(source="vote_count", read_only=True, default=0)
    voted = serializers.SerializerMethodField()
    mine = serializers.SerializerMethodField()
    showing = serializers.SerializerMethodField()

    class Meta:
        model = Film
        fields = ["id", "slug", "title", "year", "director", "country", "runtime", "genres",
                  "tagline", "poster", "palette", "status", "on_ballot", "votes", "voted", "mine", "showing"]

    def get_poster(self, f):
        return media_url(self.context.get("request"), f.poster) or f.poster_url or None

    def get_genres(self, f):
        return f.genre_list

    def get_showing(self, f):
        """{"next": <datetime>} if it's on the programme, {"screened": n} if it has played, else None."""
        up, done = self.context.get("upcoming"), self.context.get("screened")
        if up is None:
            return None
        if f.id in up:
            return {"next": up[f.id], "screened": done.get(f.id, 0)}
        if f.id in done:
            return {"next": None, "screened": done[f.id]}
        return None

    def get_mine(self, f):
        """The requesting member's own private marks, or None for visitors."""
        shelf = self.context.get("shelf")
        if shelf is None:
            return None
        return shelf.get(f.id, {"watchlist": False, "watched": False, "favourite": False, "diary": 0})

    def get_voted(self, f):
        req = self.context.get("request")
        if not req or not req.user.is_authenticated:
            return False
        ids = self.context.get("voted_ids")
        if ids is not None:
            return f.id in ids
        return f.votes.filter(user=req.user).exists()


class ScreeningCardSerializer(serializers.ModelSerializer):
    film = FilmCardSerializer(read_only=True)
    seats_left = serializers.IntegerField(read_only=True)

    class Meta:
        model = Screening
        fields = ["id", "title", "film", "starts_at", "ends_at", "venue", "address",
                  "capacity", "seats_left", "entry", "status", "is_featured"]


class CommentSerializer(serializers.ModelSerializer):
    user = MemberSerializer(read_only=True)
    replies = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ["id", "user", "body", "parent", "created_at", "replies"]
        read_only_fields = ["id", "user", "created_at", "replies"]

    def get_replies(self, c):
        qs = [r for r in c.replies.all() if not r.is_hidden]
        return CommentSerializer(qs, many=True, context=self.context).data


class FilmDetailSerializer(FilmCardSerializer):
    screenings = serializers.SerializerMethodField()
    watched_by = serializers.SerializerMethodField()
    avg_rating = serializers.SerializerMethodField()
    suggested_by = MemberSerializer(read_only=True)

    class Meta(FilmCardSerializer.Meta):
        fields = FilmCardSerializer.Meta.fields + [
            "original_title", "language", "synopsis", "trailer_url", "pitch",
            "suggested_by", "screenings", "watched_by", "avg_rating",
        ]

    def get_screenings(self, f):
        qs = f.screenings.exclude(status="cancelled").order_by("-starts_at")
        return [{"id": s.id, "starts_at": s.starts_at, "status": s.status, "venue": s.venue} for s in qs]

    def get_watched_by(self, f):
        users = User.objects.filter(log__film=f).distinct()[:24]
        return MemberSerializer(users, many=True, context=self.context).data

    def get_avg_rating(self, f):
        vals = [e.rating for e in f.log_entries.all() if e.rating]
        return round(sum(vals) / len(vals), 1) if vals else None


class ScreeningFilmSerializer(FilmCardSerializer):
    class Meta(FilmCardSerializer.Meta):
        fields = FilmCardSerializer.Meta.fields + ["synopsis", "trailer_url"]


class ScreeningDetailSerializer(ScreeningCardSerializer):
    film = ScreeningFilmSerializer(read_only=True)
    host_note = serializers.CharField(read_only=True)
    attendees = serializers.SerializerMethodField()
    my_reservation = serializers.SerializerMethodField()

    class Meta(ScreeningCardSerializer.Meta):
        fields = ScreeningCardSerializer.Meta.fields + ["host_note", "attendees", "my_reservation"]

    def get_attendees(self, s):
        users = [r.user for r in s.reservations.select_related("user__profile")[:40]]
        return MemberSerializer(users, many=True, context=self.context).data

    def get_my_reservation(self, s):
        req = self.context.get("request")
        if not req or not req.user.is_authenticated:
            return None
        r = s.reservations.filter(user=req.user).first()
        return ReservationSerializer(r, context=self.context).data if r else None


class ReservationSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)

    class Meta:
        model = Reservation
        fields = ["id", "code", "seats", "note", "created_at", "attended"]
        read_only_fields = ["id", "code", "created_at", "attended"]

    def validate_seats(self, v):
        if not 1 <= v <= 4:
            raise serializers.ValidationError("Between one and four seats per member.")
        return v


class MyReservationSerializer(ReservationSerializer):
    screening = ScreeningCardSerializer(read_only=True)

    class Meta(ReservationSerializer.Meta):
        fields = ReservationSerializer.Meta.fields + ["screening"]


class LogEntrySerializer(serializers.ModelSerializer):
    film = FilmCardSerializer(read_only=True)
    film_id = serializers.PrimaryKeyRelatedField(queryset=Film.objects.all(), source="film", write_only=True)
    user = MemberSerializer(read_only=True)

    class Meta:
        model = LogEntry
        fields = ["id", "user", "film", "film_id", "screening", "rating", "note", "watched_on", "watched_with", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

    def validate_rating(self, v):
        if v is not None and not 1 <= v <= 5:
            raise serializers.ValidationError("Rate from one to five.")
        return v


class VoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vote
        fields = ["film", "created_at"]


# ---------- booth (staff-only CMS at /api/booth/) ----------

def film_poster(request, f):
    return media_url(request, f.poster) or f.poster_url or None


class BoothFilmRefSerializer(serializers.ModelSerializer):
    """A film as it appears inside screenings and comments."""

    poster = serializers.SerializerMethodField()

    class Meta:
        model = Film
        fields = ["id", "slug", "title", "year", "director", "poster"]

    def get_poster(self, f):
        return film_poster(self.context.get("request"), f)


class BoothFilmSerializer(serializers.ModelSerializer):
    poster_src = serializers.SerializerMethodField()
    suggested_by = MemberSerializer(read_only=True)
    votes = serializers.IntegerField(source="vote_count", read_only=True, default=0)
    screenings_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Film
        fields = ["id", "slug", "title", "original_title", "year", "director", "country", "language", "runtime",
                  "genres", "tagline", "synopsis", "palette", "trailer_url", "poster", "poster_url", "poster_src",
                  "on_ballot", "status", "tmdb_id", "suggested_by", "pitch", "created_at", "votes",
                  "screenings_count"]
        read_only_fields = ["slug", "tmdb_id", "pitch", "created_at"]
        extra_kwargs = {"poster": {"required": False, "allow_null": True}}

    def get_poster_src(self, f):
        return film_poster(self.context.get("request"), f)

    def validate(self, data):
        if data.get("on_ballot"):
            data["status"] = Film.Status.VAULT  # only vault films can be voted for
        return data


class BoothReservationSerializer(serializers.ModelSerializer):
    user = MemberSerializer(read_only=True)

    class Meta:
        model = Reservation
        fields = ["id", "code", "user", "seats", "note", "attended", "created_at"]
        read_only_fields = ["note", "created_at"]


class BoothScreeningSerializer(serializers.ModelSerializer):
    film = BoothFilmRefSerializer(read_only=True)
    film_id = serializers.PrimaryKeyRelatedField(queryset=Film.objects.all(), source="film", write_only=True)
    seats_taken = serializers.SerializerMethodField()
    seats_left = serializers.SerializerMethodField()

    class Meta:
        model = Screening
        fields = ["id", "film", "film_id", "title", "starts_at", "ends_at", "venue", "address", "capacity", "entry",
                  "host_note", "is_featured", "status", "seats_taken", "seats_left"]

    def get_seats_taken(self, s):
        taken = getattr(s, "taken", None)
        return s.seats_taken if taken is None else taken

    def get_seats_left(self, s):
        return max(s.capacity - self.get_seats_taken(s), 0)


class BoothCommentSerializer(serializers.ModelSerializer):
    user = MemberSerializer(read_only=True)
    target = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ["id", "user", "body", "parent", "is_hidden", "created_at", "target"]
        read_only_fields = ["body", "parent", "created_at"]

    def get_target(self, c):
        if c.film_id:
            return {"kind": "film", "id": c.film_id, "label": c.film.title, "key": c.film.slug}
        if c.screening_id:
            return {"kind": "screening", "id": c.screening_id, "label": c.screening.film.title, "key": c.screening_id}
        return None


class BoothMemberSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    reservation_count = serializers.IntegerField(read_only=True, default=0)
    comment_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = User
        fields = ["id", "username", "email", "display_name", "avatar", "is_staff", "is_superuser", "date_joined",
                  "last_login", "reservation_count", "comment_count"]
        read_only_fields = ["username", "email", "is_superuser", "date_joined", "last_login"]

    def get_display_name(self, u):
        return MemberSerializer.get_display_name(self, u)

    def get_avatar(self, u):
        return MemberSerializer.get_avatar(self, u)
