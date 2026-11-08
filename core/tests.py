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
        self.lion = Film.objects.create(title="Lion", year=2016, status="vault", listed=True)
        self.idea = Film.objects.create(title="Some Pitch", year=2001, status="suggested", suggested_by=self.alice, listed=True)
        self.night = Screening.objects.create(film=self.lion, starts_at=timezone.now() + timedelta(days=1))
        self.r_alice = Reservation.objects.create(screening=self.night, user=self.alice, guests=["Ram"], attended=True)
        self.r_bob = Reservation.objects.create(screening=self.night, user=self.bob)
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

    def test_search_includes_tmdb_films_we_dont_have(self):
        self.as_staff()
        self.lion.tmdb_id = 334543
        self.lion.save()
        hits = {"results": [
            {"id": 334543, "title": "Lion", "release_date": "2016-11-25"},
            {"id": 9999, "title": "Lion King of Kirtipur", "release_date": "1999-01-01", "poster_path": "/p.jpg"},
        ]}
        with mock.patch("core.tmdb.get", return_value=hits):
            rows = self.api.get("/api/booth/films/?q=lion").data["results"]
        self.assertEqual([r["title"] for r in rows], ["Lion", "Lion King of Kirtipur"])
        self.assertEqual(rows[0]["id"], self.lion.pk)  # ours, not repeated from TMDB
        self.assertIsNone(rows[1]["id"])
        self.assertTrue(rows[1]["from_tmdb"])

    def test_film_strip_toggle_drives_the_home_page(self):
        self.as_staff()
        r = self.api.patch(f"/api/booth/films/{self.idea.pk}/", {"in_strip": True}, format="json")
        self.assertEqual((r.data["in_strip"], r.data["status"]), (True, "vault"))
        strip = [f["title"] for f in APIClient().get("/api/films/?strip=1").data]
        self.assertEqual(strip, ["Some Pitch"])
        self.assertEqual(self.api.get("/api/booth/films/?in_strip=1").data["count"], 1)

    def test_superusers_are_not_listed_as_members(self):
        self.as_staff()
        User.objects.create_superuser("owner", password="pw-owner-123456")
        names = {m["username"] for m in self.api.get("/api/booth/members/").data["results"]}
        self.assertNotIn("owner", names)
        self.assertIn("alice", names)
        self.assertEqual(self.api.get("/api/booth/dashboard/").data["counts"]["members"], 3)

    def test_booking_with_named_guests(self):
        carol = User.objects.create_user("carol", password="pw-carol-123456")
        api = APIClient()
        api.force_authenticate(carol)
        url = f"/api/screenings/{self.night.pk}/reserve/"
        r = api.post(url, {"guests": ["  Sita   Rai ", "", "Hari"]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["guests"], r.data["seats"]), (["Sita Rai", "Hari"], 3))
        r = api.post(url, {"guests": []}, format="json")  # changing your mind frees the seats
        self.assertEqual((r.data["guests"], r.data["seats"]), ([], 1))
        self.assertEqual(api.post(url, {"guests": ["a", "b", "c", "d"]}, format="json").status_code, 400)
        self.assertEqual(api.post(url, {"seats": 4}, format="json").data["seats"], 1)  # seats can't be asked for directly
        self.as_staff()
        res = {x["user"]["username"]: x for x in self.api.get(f"/api/booth/screenings/{self.night.pk}/reservations/").data}
        self.assertEqual(res["alice"]["guests"], ["Ram"])

    def test_members_need_approval_to_vote(self):
        self.lion.on_ballot = True
        self.lion.save()
        carol = User.objects.create_user("carol", password="pw-carol-123456")
        api = APIClient()
        api.force_authenticate(carol)
        self.assertFalse(api.get("/api/me/").data["can_vote"])
        r = api.post(f"/api/films/{self.lion.slug}/vote/")
        self.assertEqual(r.status_code, 403)
        self.assertIn("approve", r.data["detail"])
        self.as_staff()
        self.assertEqual(self.api.get("/api/booth/members/?can_vote=0").data["count"], 3)  # alice, bob, carol
        self.assertEqual(self.api.get("/api/booth/dashboard/").data["counts"]["awaiting_approval"], 3)
        r = self.api.patch(f"/api/booth/members/{carol.pk}/", {"can_vote": True}, format="json")
        self.assertTrue(r.data["can_vote"])
        api.force_authenticate(User.objects.get(pk=carol.pk))  # a fresh request loads the user anew
        self.assertEqual(api.post(f"/api/films/{self.lion.slug}/vote/").data["voted"], True)
        self.assertTrue(self.api.post(f"/api/films/{self.lion.slug}/vote/").data["voted"])  # staff never need approval

    def test_staff_can_add_a_member(self):
        self.as_staff()
        r = self.api.post("/api/booth/members/", {"username": "dipa", "display_name": "Dipa K",
                                                   "password": "garden-nights-2026"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["display_name"], r.data["can_vote"], r.data["is_staff"]), ("Dipa K", True, False))
        self.assertTrue(APIClient().post("/api/auth/token/", {"username": "dipa", "password": "garden-nights-2026"}, format="json").status_code == 200)
        self.assertEqual(self.api.post("/api/booth/members/", {"username": "dipa", "password": "garden-nights-2026"}, format="json").status_code, 400)
        self.assertEqual(self.api.post("/api/booth/members/", {"username": "x2", "password": "123"}, format="json").status_code, 400)
        self.api.force_authenticate(self.alice)
        self.assertEqual(self.api.post("/api/booth/members/", {"username": "y", "password": "garden-nights-2026"}, format="json").status_code, 403)

    def test_vault_shows_our_films_first_and_booth_lists_only_ours(self):
        self.lion.listed = True
        self.lion.tmdb_id = 334543
        self.lion.save()
        stray = Film.objects.create(title="Opened By A Visitor", year=1999, tmdb_id=777)  # not listed
        hits = {"page": 1, "total_pages": 3, "total_results": 2, "results": [
            {"id": 777, "title": "Opened By A Visitor", "release_date": "1999-01-01"},
            {"id": 888, "title": "Something Else", "release_date": "2001-01-01"}]}
        with mock.patch("core.tmdb.get", return_value=hits):
            first = APIClient().get("/api/catalogue/").data["results"]
            second = APIClient().get("/api/catalogue/?page=2").data["results"]
        self.assertEqual([r["title"] for r in first], ["Lion", "Opened By A Visitor", "Something Else"])
        self.assertTrue(first[0]["ours"])
        self.assertNotIn("Lion", [r["title"] for r in second])
        self.as_staff()
        listed = [f["title"] for f in self.api.get("/api/booth/films/").data["results"]]
        self.assertIn("Lion", listed)
        self.assertNotIn("Opened By A Visitor", listed)
        with mock.patch("core.tmdb.details", return_value={"tmdb_id": 777, "title": "Opened By A Visitor", "year": 1999}):
            r = self.api.post("/api/booth/films/import/", {"tmdb_id": 777}, format="json")
        self.assertEqual((r.status_code, r.data["id"], r.data["listed"]), (201, stray.pk, True))

    def test_vault_filters_by_several_genres(self):
        self.lion.genres = "Drama, Romance"
        self.lion.save()
        Film.objects.create(title="Only Drama", year=2000, genres="Drama", listed=True)
        meta = {"genres": [{"id": 18, "name": "Drama"}, {"id": 10749, "name": "Romance"}]}
        calls = []

        def fake(path, **params):
            calls.append((path, params))
            return meta if path == "/genre/movie/list" else {"page": 1, "total_pages": 1, "results": []}
        with mock.patch("core.tmdb.get", side_effect=fake):
            titles = [r["title"] for r in APIClient().get("/api/catalogue/?genre=18,10749").data["results"]]
        self.assertEqual(titles, ["Lion"])  # both genres, not either
        self.assertEqual(next(p for path, p in calls if path == "/discover/movie")["with_genres"], "18,10749")

    def test_home_page_keeps_a_featured_night_after_its_date(self):
        self.night.starts_at = timezone.now() - timedelta(days=2)
        self.night.save()
        self.assertIsNone(APIClient().get("/api/site/").data["next_screening"])
        self.night.is_featured = True
        self.night.save()
        self.assertEqual(APIClient().get("/api/site/").data["next_screening"]["id"], self.night.pk)
        later = Screening.objects.create(film=self.idea, starts_at=timezone.now() + timedelta(days=5))
        self.assertEqual(APIClient().get("/api/site/").data["next_screening"]["id"], later.pk)  # a real next night wins
