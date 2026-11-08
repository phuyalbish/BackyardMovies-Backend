"""
The Projection Booth API: staff-only endpoints under /api/booth/ that power the React booth.
Every view requires is_staff (DRF's IsAdminUser). The public API in views.py is untouched.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, ProtectedError, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from . import tmdb
from .models import Comment, Film, Reservation, Screening, SiteSettings, Vote
from .serializers import (
    BoothCommentSerializer, BoothFilmSerializer, BoothMemberSerializer, BoothReservationSerializer,
    BoothScreeningSerializer, SiteSettingsSerializer,
)

User = get_user_model()


class BoothPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


class BoothMixin:
    permission_classes = [IsAdminUser]
    pagination_class = BoothPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def flag(self, name):
        """?name=1 -> True, ?name=0 -> False, absent -> None."""
        v = self.request.query_params.get(name)
        return None if v in (None, "") else v in ("1", "true", "True")


# ---------- films ----------

class FilmViewSet(BoothMixin, viewsets.ModelViewSet):
    serializer_class = BoothFilmSerializer
    ORDERS = {"title": "title", "-created_at": "-created_at", "-votes": "-vote_count", "votes": "vote_count",
              "created_at": "created_at", "-year": "-year", "year": "year"}

    def get_queryset(self):
        qs = (Film.objects.annotate(vote_count=Count("votes", distinct=True),
                                    screenings_count=Count("screenings", distinct=True))
              .select_related("suggested_by__profile"))
        p = self.request.query_params
        if q := p.get("q", "").strip():
            qs = qs.filter(Q(title__icontains=q) | Q(original_title__icontains=q) | Q(director__icontains=q))
        if st := p.get("status"):
            qs = qs.filter(status=st)
        if (b := self.flag("on_ballot")) is not None:
            qs = qs.filter(on_ballot=b)
        return qs.order_by(self.ORDERS.get(p.get("order"), "-created_at"), "title")

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response({"detail": "This film has screenings. Delete those first."}, status=status.HTTP_409_CONFLICT)

    def fresh(self, film):
        return self.get_serializer(self.get_queryset().get(pk=film.pk)).data

    @action(detail=True, methods=["post"], url_path="reset-votes")
    def reset_votes(self, request, pk=None):
        film = self.get_object()
        Vote.objects.filter(film=film).delete()
        return Response(self.fresh(film))

    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None):
        """Fill the film from TMDB. overwrite=true also replaces text that is already set."""
        film = self.get_object()
        try:
            tid = film.tmdb_id or tmdb.match([film.title, film.original_title], film.year)
            if not tid:
                return Response({"detail": "No match on TMDB for this title and year."}, status=400)
            if Film.objects.filter(tmdb_id=tid).exclude(pk=film.pk).exists():
                return Response({"detail": "Another film is already linked to that TMDB entry."}, status=400)
            film.apply_tmdb({**tmdb.details(tid), "tmdb_id": tid}, overwrite=bool(request.data.get("overwrite")))
        except tmdb.TMDBError as e:
            return Response({"detail": str(e)}, status=502)
        return Response(self.fresh(film))

    @action(detail=False, methods=["post"], url_path="import")
    def import_film(self, request):
        """Add a film from a TMDB id (from the /api/catalogue/ search)."""
        from .views import import_film  # views imports nothing from here; local import keeps it one-way

        try:
            tid = int(request.data.get("tmdb_id"))
        except (TypeError, ValueError):
            return Response({"tmdb_id": ["A TMDB id is required."]}, status=400)
        existed = Film.objects.filter(tmdb_id=tid).exists()
        try:
            film = import_film(tid)
        except tmdb.TMDBError as e:
            return Response({"detail": str(e)}, status=502)
        return Response(self.fresh(film), status=200 if existed else 201)


# ---------- screenings and reservations ----------

class ScreeningViewSet(BoothMixin, viewsets.ModelViewSet):
    serializer_class = BoothScreeningSerializer

    def get_queryset(self):
        qs = Screening.objects.select_related("film").annotate(taken=Coalesce(Sum("reservations__seats"), 0))
        st = self.request.query_params.get("status")
        if st:
            qs = qs.filter(status=st)
        # upcoming nights soonest first; everything else newest first
        return qs.order_by("starts_at" if st == "upcoming" else "-starts_at")

    def fresh(self, s):
        return self.get_serializer(self.get_queryset().get(pk=s.pk)).data

    def destroy(self, request, *args, **kwargs):
        s = self.get_object()
        if s.reservations.exists():
            return Response({"detail": "People have booked this night. Cancel it instead, or remove the bookings first."},
                            status=status.HTTP_409_CONFLICT)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def screen(self, request, pk=None):
        s = self.get_object()
        logged = s.mark_screened()
        return Response({**self.fresh(s), "logged": logged})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        s = self.get_object()
        s.status = Screening.Status.CANCELLED
        s.save(update_fields=["status"])
        return Response(self.fresh(s))

    @action(detail=True, methods=["get"])
    def reservations(self, request, pk=None):
        s = self.get_object()
        qs = s.reservations.select_related("user__profile").order_by("-created_at")
        return Response(BoothReservationSerializer(qs, many=True, context={"request": request}).data)


class ReservationViewSet(BoothMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = BoothReservationSerializer
    queryset = Reservation.objects.select_related("user__profile")


# ---------- comments ----------

class CommentViewSet(BoothMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                     mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = BoothCommentSerializer

    def get_queryset(self):
        qs = Comment.objects.select_related("user__profile", "film", "screening__film").order_by("-created_at")
        if (h := self.flag("hidden")) is not None:
            qs = qs.filter(is_hidden=h)
        if q := self.request.query_params.get("q", "").strip():
            qs = qs.filter(Q(body__icontains=q) | Q(user__username__icontains=q) | Q(user__profile__display_name__icontains=q))
        return qs


# ---------- members ----------

class MemberViewSet(BoothMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                    viewsets.GenericViewSet):
    serializer_class = BoothMemberSerializer

    def get_queryset(self):
        qs = (User.objects.select_related("profile")
              .annotate(reservation_count=Count("reservations", distinct=True),
                        comment_count=Count("comments", distinct=True))
              .order_by("-date_joined"))
        if q := self.request.query_params.get("q", "").strip():
            qs = qs.filter(Q(username__icontains=q) | Q(profile__display_name__icontains=q) | Q(email__icontains=q))
        if self.flag("staff"):
            qs = qs.filter(is_staff=True)
        return qs

    def update(self, request, *args, **kwargs):
        member = self.get_object()
        if request.data.get("is_staff") in (False, "false", "0", 0):
            if member.pk == request.user.pk:
                return Response({"detail": "You can't remove your own staff access."}, status=400)
            if member.is_superuser:
                return Response({"detail": "Superusers keep staff access."}, status=400)
        kwargs["partial"] = True
        return super().update(request, *args, **kwargs)


# ---------- dashboard and settings ----------

@api_view(["GET"])
@permission_classes([IsAdminUser])
def dashboard(request):
    c = {"request": request}
    # The next night; failing that, a past night nobody has closed yet (it still needs "mark screened").
    nxt = Screening.next_up() or Screening.objects.filter(status=Screening.Status.UPCOMING).order_by("-starts_at").first()
    tonight = None
    if nxt:
        nxt = Screening.objects.select_related("film").annotate(taken=Coalesce(Sum("reservations__seats"), 0)).get(pk=nxt.pk)
        res = nxt.reservations.select_related("user__profile").order_by("-created_at")
        tonight = {**BoothScreeningSerializer(nxt, context=c).data,
                   "reservations": BoothReservationSerializer(res, many=True, context=c).data,
                   "overdue": nxt.starts_at < timezone.now() - timedelta(hours=4)}
    ballot = (Film.objects.filter(on_ballot=True, status=Film.Status.VAULT)
              .annotate(vote_count=Count("votes", distinct=True), screenings_count=Count("screenings", distinct=True))
              .order_by("-vote_count", "title")[:8])
    recent = Comment.objects.select_related("user__profile", "film", "screening__film").order_by("-created_at")[:6]
    return Response({
        "tonight": tonight,
        "ballot": BoothFilmSerializer(ballot, many=True, context=c).data,
        "recent_comments": BoothCommentSerializer(recent, many=True, context=c).data,
        "counts": {
            "members": User.objects.count(),
            "films": Film.objects.filter(status=Film.Status.VAULT).count(),
            "suggestions": Film.objects.filter(status=Film.Status.SUGGESTED).count(),
            "hidden_comments": Comment.objects.filter(is_hidden=True).count(),
            "upcoming": Screening.objects.filter(status=Screening.Status.UPCOMING).count(),
            "on_ballot": Film.objects.filter(on_ballot=True, status=Film.Status.VAULT).count(),
        },
    })


@api_view(["GET", "PATCH"])
@permission_classes([IsAdminUser])
def settings_view(request):
    obj = SiteSettings.load()
    if request.method == "PATCH":
        s = SiteSettingsSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)
    return Response(SiteSettingsSerializer(obj).data)


router = SimpleRouter()
router.register("films", FilmViewSet, basename="booth-film")
router.register("screenings", ScreeningViewSet, basename="booth-screening")
router.register("reservations", ReservationViewSet, basename="booth-reservation")
router.register("comments", CommentViewSet, basename="booth-comment")
router.register("members", MemberViewSet, basename="booth-member")
