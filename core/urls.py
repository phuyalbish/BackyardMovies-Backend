from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views as v

urlpatterns = [
    path("site/", v.site),
    path("genres/", v.genres),
    path("feed/", v.feed),
    path("auth/register/", v.register),
    path("auth/token/", TokenObtainPairView.as_view()),
    path("auth/token/refresh/", TokenRefreshView.as_view()),
    path("me/", v.me),
    path("me/reservations/", v.my_reservations),
    path("me/films/", v.my_films),
    path("me/films/<slug:slug>/", v.my_film_mark),
    path("films/", v.film_list),
    path("catalogue/", v.catalogue),
    path("catalogue/meta/", v.catalogue_meta),
    path("films/tmdb/<int:tmdb_id>/", v.film_from_tmdb),
    path("films/<slug:slug>/", v.film_detail),
    path("films/<slug:slug>/vote/", v.film_vote),
    path("films/<slug:slug>/comments/", v.film_comments),
    path("ballot/", v.ballot),
    path("screenings/", v.screening_list),
    path("screenings/<int:pk>/", v.screening_detail),
    path("screenings/<int:pk>/reserve/", v.reserve),
    path("screenings/<int:pk>/comments/", v.screening_comments),
    path("comments/<int:pk>/", v.comment_delete),
    path("log/", v.log_list),
    path("log/<int:pk>/", v.log_delete),
    path("members/<str:username>/", v.member),
]
