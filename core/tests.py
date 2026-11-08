from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Comment, Film, LogEntry, Reservation, Screening, Shelf, SiteSettings, Vote

User = get_user_model()


class BoothAPITests(TestCase):
    """The staff-only Projection Booth API under /api/booth/."""

    def setUp(self):
        self.staff = User.objects.create_user("host", password="pw-host-123456", is_staff=True)
        self.alice = User.objects.create_user("alice", password="pw-alice-123456")
        self.bob = User.objects.create_user("bob", password="pw-bob-123456")
        self.lion = Film.objects.create(title="Lion", year=2016, status="vault")
        self.idea = Film.objects.create(title="Some Pitch", year=2001, status="suggested", suggested_by=self.alice)
        self.night = Screening.objects.create(film=self.lion, starts_at=timezone.now() + timedelta(days=1))
        self.r_alice = Reservation.objects.create(screening=self.night, user=self.alice, seats=2, attended=True)
        self.r_bob = Reservation.objects.create(screening=self.night, user=self.bob, seats=1)
        self.comment = Comment.objects.create(user=self.bob, film=self.lion, body="Bring tissues.")
        self.api = APIClient()

    def as_staff(self):
        self.api.force_authenticate(self.staff)

    def test_non_staff_are_blocked(self):
        self.assertEqual(self.api.get("/api/booth/films/").status_code, 401)
        self.api.force_authenticate(self.alice)
        self.assertEqual(self.api.get("/api/booth/films/").status_code, 403)
        self.assertEqual(self.api.post(f"/api/booth/screenings/{self.night.pk}/screen/").status_code, 403)
        self.assertEqual(self.api.get("/api/booth/dashboard/").status_code, 403)

    def test_staff_lists_films_paginated_and_filtered(self):
        self.as_staff()
        r = self.api.get("/api/booth/films/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data), {"count", "next", "previous", "results"})
        self.assertEqual(r.data["count"], 2)
        self.assertEqual(len(self.api.get("/api/booth/films/?page_size=1").data["results"]), 1)
        titles = [f["title"] for f in self.api.get("/api/booth/films/?status=suggested").data["results"]]
        self.assertEqual(titles, ["Some Pitch"])

    def test_putting_a_suggestion_on_the_ballot_moves_it_to_the_vault(self):
        self.as_staff()
        r = self.api.patch(f"/api/booth/films/{self.idea.pk}/", {"on_ballot": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.idea.refresh_from_db()
        self.assertTrue(self.idea.on_ballot)
        self.assertEqual(self.idea.status, "vault")

    def test_reset_votes(self):
        self.as_staff()
        Vote.objects.create(film=self.lion, user=self.alice)
        r = self.api.post(f"/api/booth/films/{self.lion.pk}/reset-votes/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["votes"], 0)

    def test_mark_screened_logs_attendees_once(self):
        self.as_staff()
        r = self.api.post(f"/api/booth/screenings/{self.night.pk}/screen/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "done")
        self.assertEqual(r.data["logged"], 1)
        entry = LogEntry.objects.get()
        self.assertEqual((entry.user, entry.screening, entry.watched_with), (self.alice, self.night, "Backyard Movies"))
        shelf = Shelf.objects.get(user=self.alice, film=self.lion)
        self.assertTrue(shelf.watched)
        self.assertFalse(shelf.watchlist)
        self.assertFalse(LogEntry.objects.filter(user=self.bob).exists())
        again = self.api.post(f"/api/booth/screenings/{self.night.pk}/screen/")
        self.assertEqual(again.data["logged"], 0)
        self.assertEqual(LogEntry.objects.count(), 1)

    def test_screening_list_reports_seats(self):
        self.as_staff()
        row = self.api.get("/api/booth/screenings/?status=upcoming").data["results"][0]
        self.assertEqual((row["seats_taken"], row["seats_left"]), (3, 27))
        res = self.api.get(f"/api/booth/screenings/{self.night.pk}/reservations/").data
        self.assertEqual({r["user"]["username"] for r in res}, {"alice", "bob"})

    def test_create_and_cancel_screening(self):
        self.as_staff()
        r = self.api.post("/api/booth/screenings/", {
            "film_id": self.idea.pk, "starts_at": (timezone.now() + timedelta(days=9)).isoformat(), "capacity": 20,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["film"]["title"], "Some Pitch")
        c = self.api.post(f"/api/booth/screenings/{r.data['id']}/cancel/")
        self.assertEqual(c.data["status"], "cancelled")

    def test_staff_cannot_demote_themselves(self):
        self.as_staff()
        r = self.api.patch(f"/api/booth/members/{self.staff.pk}/", {"is_staff": False}, format="json")
        self.assertEqual(r.status_code, 400)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_staff)
        r = self.api.patch(f"/api/booth/members/{self.alice.pk}/", {"is_staff": True, "is_superuser": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.is_staff)
        self.assertFalse(self.alice.is_superuser)

    def test_member_list_counts(self):
        self.as_staff()
        rows = {m["username"]: m for m in self.api.get("/api/booth/members/").data["results"]}
        self.assertEqual(rows["bob"]["comment_count"], 1)
        self.assertEqual(rows["alice"]["reservation_count"], 1)

    def test_settings_get_and_patch(self):
        self.as_staff()
        r = self.api.patch("/api/booth/settings/", {"tagline": "Under the stars"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(SiteSettings.load().tagline, "Under the stars")
        self.assertIn("venue_name", self.api.get("/api/booth/settings/").data)

    def test_attended_and_hiding_a_comment(self):
        self.as_staff()
        r = self.api.patch(f"/api/booth/reservations/{self.r_bob.pk}/", {"attended": True}, format="json")
        self.assertTrue(r.data["attended"])
        self.api.patch(f"/api/booth/comments/{self.comment.pk}/", {"is_hidden": True}, format="json")
        self.assertEqual(self.api.get("/api/booth/comments/?hidden=1").data["count"], 1)
        public = APIClient().get(f"/api/films/{self.lion.slug}/comments/").data
        self.assertEqual(public, [])

    def test_deleting_a_film_with_screenings_is_refused(self):
        self.as_staff()
        self.assertEqual(self.api.delete(f"/api/booth/films/{self.lion.pk}/").status_code, 409)
        self.assertEqual(self.api.delete(f"/api/booth/films/{self.idea.pk}/").status_code, 204)

    def test_deleting_a_booked_screening_is_refused(self):
        self.as_staff()
        self.assertEqual(self.api.delete(f"/api/booth/screenings/{self.night.pk}/").status_code, 409)

    def test_dashboard(self):
        self.as_staff()
        d = self.api.get("/api/booth/dashboard/").data
        self.assertEqual(d["tonight"]["id"], self.night.pk)
        self.assertEqual(len(d["tonight"]["reservations"]), 2)
        self.assertEqual(d["counts"]["suggestions"], 1)

    def test_import_from_tmdb(self):
        self.as_staff()
        details = {"tmdb_id": 548, "title": "Rashomon", "original_title": "羅生門", "year": 1950,
                   "director": "Akira Kurosawa", "country": "Japan", "language": "Japanese", "runtime": 88,
                   "genres": "Crime, Drama", "tagline": "", "synopsis": "Rain.", "poster_url": "https://image/x.jpg"}
        with mock.patch("core.tmdb.details", return_value=details):
            first = self.api.post("/api/booth/films/import/", {"tmdb_id": 548}, format="json")
            second = self.api.post("/api/booth/films/import/", {"tmdb_id": 548}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["director"], "Akira Kurosawa")
        self.assertEqual(Film.objects.filter(tmdb_id=548).count(), 1)
