from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from . import tmdb
from .models import Comment, Film, LogEntry, Reservation, Screening, Shelf, SiteSettings, Vote
from .serializers import (
    CommentSerializer, FilmCardSerializer,
    FilmDetailSerializer, LogEntrySerializer, MemberSerializer, MeSerializer,
    MyReservationSerializer, RegisterSerializer, ReservationSerializer,
    ScreeningCardSerializer, ScreeningDetailSerializer, SiteSettingsSerializer,
)

User = get_user_model()


def ctx(request, **extra):
    c = {"request": request}
    # Which films are on the programme or have already played, for the posters' stamps.
    upcoming, screened = {}, {}
    for fid, status, at in (Screening.objects.filter(status__in=["upcoming", "done"])
                            .order_by("starts_at").values_list("film_id", "status", "starts_at")):
        if status == "upcoming":
            upcoming.setdefault(fid, at)
        else:
            screened[fid] = screened.get(fid, 0) + 1
    c["upcoming"], c["screened"] = upcoming, screened
    if request.user.is_authenticated:
        c["voted_ids"] = set(Vote.objects.filter(user=request.user).values_list("film_id", flat=True))
        logged = dict(LogEntry.objects.filter(user=request.user).values("film_id")
                      .annotate(n=Count("id")).values_list("film_id", "n"))
        c["shelf"] = {s["film_id"]: {**{m: s[m] for m in Shelf.MARKS}, "diary": logged.get(s["film_id"], 0)}
                      for s in Shelf.objects.filter(user=request.user).values("film_id", *Shelf.MARKS)}
    c.update(extra)
    return c


def films_qs():
    return Film.objects.annotate(vote_count=Count("votes", distinct=True))


# ---------- site ----------

@api_view(["GET"])
@permission_classes([AllowAny])
def site(request):
    data = SiteSettingsSerializer(SiteSettings.load()).data
    data["stats"] = {
        "members": User.objects.count(),
        "nights": Screening.objects.filter(status="done").count(),
        "films": Film.objects.filter(status="vault").count(),
    }
    nxt = (Screening.objects.filter(status="upcoming", starts_at__gte=timezone.now() - timezone.timedelta(hours=4))
           .order_by("-is_featured", "starts_at").select_related("film").first())
    data["next_screening"] = ScreeningDetailSerializer(nxt, context=ctx(request)).data if nxt else None
    return Response(data)


@api_view(["GET"])
@permission_classes([AllowAny])
def genres(request):
    names = set()
    for g in Film.objects.filter(status="vault").values_list("genres", flat=True):
        names.update(x.strip() for x in g.split(",") if x.strip())
    return Response(sorted(names))


@api_view(["GET"])
@permission_classes([AllowAny])
def feed(request):
    qs = (Comment.objects.filter(is_hidden=False, parent__isnull=True)
          .select_related("user__profile", "film", "screening__film").order_by("-created_at")[:12])
    out = []
    for c in qs:
        item = CommentSerializer(c, context={"request": request}).data
        item.pop("replies", None)
        if c.film_id:
            item["on"] = {"kind": "film", "label": c.film.title, "key": c.film.slug}
        elif c.screening_id:
            item["on"] = {"kind": "screening", "label": c.screening.film.title, "key": c.screening_id}
        out.append(item)
    return Response(out)


# ---------- auth ----------

@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    s = RegisterSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    user = s.save()
    return Response(MeSerializer(user, context={"request": request}).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def me(request):
    user = request.user
    if request.method == "PATCH":
        if "avatar" in request.FILES:
            user.profile.avatar = request.FILES["avatar"]
            user.profile.save()
        payload = {k: v for k, v in request.data.items() if k != "avatar"}
        profile = {k: payload.pop(k) for k in ["display_name", "bio", "favourite_film", "city", "favourites_public"] if k in payload}
        if isinstance(payload.get("profile"), dict):
            profile.update(payload.pop("profile"))
        s = MeSerializer(user, data={**payload, "profile": profile}, partial=True, context={"request": request})
        s.is_valid(raise_exception=True)
        s.save()
    data = MeSerializer(user, context={"request": request}).data
    data["profile"]["avatar"] = request.build_absolute_uri(user.profile.avatar.url) if user.profile.avatar else None
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_reservations(request):
    qs = Reservation.objects.filter(user=request.user).select_related("screening__film").order_by("screening__starts_at")
    return Response(MyReservationSerializer(qs, many=True, context=ctx(request)).data)


# ---------- films ----------

@api_view(["GET"])
@permission_classes([AllowAny])
def film_list(request):
    qs = films_qs().filter(status="vault")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(director__icontains=q) | Q(original_title__icontains=q))
    g = request.GET.get("genre")
    if g:
        qs = qs.filter(genres__icontains=g)
    d = request.GET.get("decade")
    if d and d.isdigit():
        qs = qs.filter(year__gte=int(d), year__lt=int(d) + 10)
    order = request.GET.get("order", "title")
    qs = qs.order_by({"year": "year", "-year": "-year", "votes": "-vote_count"}.get(order, "title"))
    return Response(FilmCardSerializer(qs, many=True, context=ctx(request)).data)


# ---------- the world catalogue (TMDB) ----------

SORTS = {
    "popular": "popularity.desc",
    "rated": "vote_average.desc",
    "newest": "primary_release_date.desc",
    "oldest": "primary_release_date.asc",
    "title": "title.asc",
}


def import_film(tmdb_id):
    """Get or create the local Film for a TMDB id, filled with TMDB's details."""
    f = Film.objects.filter(tmdb_id=tmdb_id).first()
    if f:
        return f
    d = tmdb.details(tmdb_id)
    f = Film.objects.filter(tmdb_id__isnull=True, title__iexact=d["title"], year=d["year"]).first() or Film(status="vault")
    for k, v in d.items():
        if v and not getattr(f, k, None):
            setattr(f, k, v)
    f.tmdb_id = d["tmdb_id"]
    f.save()
    return f


@api_view(["GET"])
@permission_classes([AllowAny])
def catalogue(request):
    """Search or browse every film on TMDB, merged with what we know locally (votes, stamps, your marks)."""
    q = request.GET.get("q", "").strip()
    page = max(1, min(int(request.GET.get("page") or 1), 500))
    genre, decade, country = request.GET.get("genre"), request.GET.get("decade"), request.GET.get("country")
    try:
        if q:
            data = tmdb.get("/search/movie", query=q, page=page, include_adult="false")
        else:
            sort = SORTS.get(request.GET.get("sort"), SORTS["popular"])
            d = int(decade) if decade and decade.isdigit() else None
            params = {"page": page, "sort_by": sort, "include_adult": "false",
                      "with_genres": genre, "with_origin_country": country}
            if d:
                params["primary_release_date.gte"] = f"{d}-01-01"
                params["primary_release_date.lte"] = f"{d + 9}-12-31"
            if sort == SORTS["newest"] and not d:
                params["primary_release_date.lte"] = timezone.localdate().isoformat()  # skip unreleased films
            if sort == SORTS["rated"]:
                params["vote_count.gte"] = 10 if country else 150  # a 10/10 from three people isn't "top rated"
            elif sort != SORTS["popular"]:
                params["vote_count.gte"] = 5
            data = tmdb.get("/discover/movie", **params)
    except tmdb.TMDBError as e:
        return Response({"detail": str(e)}, status=502)

    cards = [tmdb.card(m) for m in data.get("results", [])]
    if q and (genre or decade):  # TMDB search can't filter, so narrow the page here
        d = int(decade) if decade and decade.isdigit() else None
        cards = [c for c in cards if (not genre or int(genre) in c["genre_ids"])
                 and (not d or (c["year"] and d <= c["year"] < d + 10))]
    local = {f.tmdb_id: f for f in films_qs().filter(tmdb_id__in=[c["tmdb_id"] for c in cards])}
    c = ctx(request)
    out = []
    for card in cards:
        f = local.get(card["tmdb_id"])
        if f:
            mine = FilmCardSerializer(f, context=c).data
            card = {**card, **{k: mine[k] for k in ("id", "slug", "votes", "voted", "on_ballot", "showing", "mine", "director", "palette")},
                    "poster": mine["poster"] or card["poster"]}
        else:
            card = {**card, "id": None, "slug": None, "votes": 0, "on_ballot": False, "showing": None,
                    "mine": {"watchlist": False, "watched": False, "favourite": False, "diary": 0} if request.user.is_authenticated else None}
        out.append(card)
    return Response({"results": out, "page": data.get("page", page), "total_pages": min(data.get("total_pages", 1), 500),
                     "total": data.get("total_results", len(out))})


@api_view(["GET"])
@permission_classes([AllowAny])
def catalogue_meta(request):
    """Genres and countries for the vault filters."""
    try:
        genres = tmdb.get("/genre/movie/list", language="en")["genres"]
        countries = sorted(tmdb.get("/configuration/countries", language="en-US"), key=lambda c: c["english_name"])
    except tmdb.TMDBError as e:
        return Response({"detail": str(e)}, status=502)
    return Response({"genres": genres, "countries": [{"code": c["iso_3166_1"], "name": c["english_name"]} for c in countries]})


@api_view(["GET"])
@permission_classes([AllowAny])
def film_from_tmdb(request, tmdb_id):
    """Open a TMDB film on our site: creates the local record the first time."""
    try:
        f = import_film(tmdb_id)
    except tmdb.TMDBError as e:
        return Response({"detail": str(e)}, status=502)
    return Response({"slug": f.slug})


@api_view(["GET"])
@permission_classes([AllowAny])
def film_detail(request, slug):
    f = get_object_or_404(films_qs().exclude(status="rejected"), slug=slug)
    return Response(FilmDetailSerializer(f, context=ctx(request)).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_films(request):
    """The member's private lists. Never exposed on public profiles."""
    rows = list(Shelf.objects.filter(user=request.user))
    c = ctx(request)
    films = {f.id: f for f in films_qs().filter(pk__in=[r.film_id for r in rows])}
    cards = {fid: FilmCardSerializer(f, context=c).data for fid, f in films.items()}
    out = {m: [cards[r.film_id] for r in rows if getattr(r, m) and r.film_id in cards] for m in Shelf.MARKS}
    # Watched carries the diary: every entry for each watched film, newest first.
    entries = {}
    for e in LogEntry.objects.filter(user=request.user, film_id__in=[c["id"] for c in out["watched"]]):
        entries.setdefault(e.film_id, []).append({"id": e.id, "rating": e.rating, "note": e.note,
                                                  "watched_on": e.watched_on, "watched_with": e.watched_with,
                                                  "screening": e.screening_id})
    marked = {r.film_id: r.updated_at for r in rows}
    out["watched"] = sorted(
        [{**c, "diary": entries.get(c["id"], [])} for c in out["watched"]],
        key=lambda c: str(c["diary"][0]["watched_on"]) if c["diary"] else marked[c["id"]].date().isoformat(),
        reverse=True,
    )
    for c in out["watched"]:
        c["marked_on"] = marked[c["id"]].date()
    return Response(out)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def my_film_mark(request, slug):
    """Set marks on a film, e.g. {"watchlist": true}. Unknown keys are ignored."""
    f = get_object_or_404(Film, slug=slug, status="vault")
    s, _ = Shelf.objects.get_or_create(user=request.user, film=f)
    for m in Shelf.MARKS:
        if m in request.data:
            setattr(s, m, bool(request.data[m]))
    if s.watched and "watched" in request.data and "watchlist" not in request.data:
        s.watchlist = False  # seen it, so it comes off the watchlist
    if "watched" in request.data and not s.watched:
        # Not watched any more: the diary lines for it go too.
        LogEntry.objects.filter(user=request.user, film=f).delete()
    diary = LogEntry.objects.filter(user=request.user, film=f).count()
    if not any(getattr(s, m) for m in Shelf.MARKS):
        s.delete()
        return Response({**{m: False for m in Shelf.MARKS}, "diary": diary})
    s.save()
    return Response({**{m: getattr(s, m) for m in Shelf.MARKS}, "diary": diary})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def film_vote(request, slug):
    f = get_object_or_404(Film, slug=slug, status="vault")
    if not f.on_ballot:
        return Response({"detail": "This film isn't on the ballot right now."}, status=400)
    vote = Vote.objects.filter(film=f, user=request.user).first()
    if vote:
        vote.delete()
        voted = False
    else:
        Vote.objects.create(film=f, user=request.user)
        voted = True
    return Response({"voted": voted, "votes": f.votes.count()})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ballot(request):
    """Members only. Exactly the films the hosts ticked "On the ballot", most votes first."""
    qs = films_qs().filter(status="vault", on_ballot=True).order_by("-vote_count", "title")
    return Response({"ranked": FilmCardSerializer(qs, many=True, context=ctx(request)).data})


# ---------- screenings ----------

@api_view(["GET"])
@permission_classes([AllowAny])
def screening_list(request):
    qs = Screening.objects.select_related("film").exclude(status="cancelled")
    when = request.GET.get("when", "upcoming")
    if when == "past":
        qs = qs.filter(status="done").order_by("-starts_at")
    else:
        qs = qs.filter(status="upcoming").order_by("starts_at")
    return Response(ScreeningCardSerializer(qs, many=True, context=ctx(request)).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def screening_detail(request, pk):
    s = get_object_or_404(Screening.objects.select_related("film"), pk=pk)
    return Response(ScreeningDetailSerializer(s, context=ctx(request)).data)


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def reserve(request, pk):
    s = get_object_or_404(Screening, pk=pk)
    existing = Reservation.objects.filter(screening=s, user=request.user).first()
    if request.method == "DELETE":
        if existing:
            existing.delete()
        return Response(status=204)
    if s.status != "upcoming":
        return Response({"detail": "This screening is not taking reservations."}, status=400)
    data = ReservationSerializer(data=request.data or {"seats": 1})
    data.is_valid(raise_exception=True)
    seats = data.validated_data.get("seats", 1)
    freed = existing.seats if existing else 0
    if seats > s.seats_left + freed:
        return Response({"detail": f"Only {s.seats_left + freed} seats left under the sky."}, status=400)
    if existing:
        existing.seats = seats
        existing.note = data.validated_data.get("note", existing.note)
        existing.save()
        r = existing
    else:
        r = Reservation.objects.create(screening=s, user=request.user, seats=seats,
                                       note=data.validated_data.get("note", ""))
    return Response(ReservationSerializer(r).data, status=201)


# ---------- comments ----------

def comment_thread(request, **target):
    if request.method == "POST":
        if not request.user.is_authenticated:
            return Response({"detail": "Sign in to join the conversation."}, status=401)
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response({"body": ["Say something first."]}, status=400)
        parent = None
        pid = request.data.get("parent")
        if pid:
            parent = get_object_or_404(Comment, pk=pid, **target)
        c = Comment.objects.create(user=request.user, body=body[:2000], parent=parent, **target)
        return Response(CommentSerializer(c, context={"request": request}).data, status=201)
    qs = (Comment.objects.filter(parent__isnull=True, is_hidden=False, **target)
          .select_related("user__profile").prefetch_related("replies__user__profile").order_by("-created_at"))
    return Response(CommentSerializer(qs, many=True, context={"request": request}).data)


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def film_comments(request, slug):
    return comment_thread(request, film=get_object_or_404(Film, slug=slug))


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def screening_comments(request, pk):
    return comment_thread(request, screening=get_object_or_404(Screening, pk=pk))



@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def comment_delete(request, pk):
    c = get_object_or_404(Comment, pk=pk)
    if c.user_id != request.user.id and not request.user.is_staff:
        return Response({"detail": "Not your comment."}, status=403)
    c.delete()
    return Response(status=204)


# ---------- logbook ----------

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def log_list(request):
    if request.method == "POST":
        s = LogEntrySerializer(data=request.data, context=ctx(request))
        s.is_valid(raise_exception=True)
        entry = s.save(user=request.user)
        # A diary entry means you've seen it: tick "watched" and take it off the watchlist.
        Shelf.objects.update_or_create(user=request.user, film=entry.film, defaults={"watched": True, "watchlist": False})
        return Response(s.data, status=201)
    qs = LogEntry.objects.filter(user=request.user).select_related("film")
    return Response(LogEntrySerializer(qs, many=True, context=ctx(request)).data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def log_delete(request, pk):
    get_object_or_404(LogEntry, pk=pk, user=request.user).delete()
    return Response(status=204)


# ---------- members ----------

@api_view(["GET"])
@permission_classes([AllowAny])
def member(request, username):
    u = get_object_or_404(User.objects.select_related("profile"), username=username)
    p = u.profile
    return Response({
        **MemberSerializer(u, context={"request": request}).data,
        "bio": p.bio, "city": p.city, "favourite_film": p.favourite_film, "date_joined": u.date_joined,
        "stats": {
            "nights": Reservation.objects.filter(user=u, screening__status="done").count(),
            "comments": Comment.objects.filter(user=u, is_hidden=False).count(),
        },
        # Favourites are private unless the member has switched them public.
        "favourites": FilmCardSerializer(
            films_qs().filter(shelved__user=u, shelved__favourite=True).order_by("-shelved__updated_at"),
            many=True, context={"request": request}).data if p.favourites_public else None,
    })
