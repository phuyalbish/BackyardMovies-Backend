from django.contrib import admin, messages
from django.db.models import Count, Sum
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import Comment, Film, Reservation, Screening, SiteSettings

admin.site.site_header = "Backyard Movies · Projection Booth"
admin.site.site_title = "Projection Booth"
admin.site.index_title = "Run the night"


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Voice", {"fields": ("tagline", "hero_quote", "hero_quote_author", "about")}),
        ("Venue", {"fields": ("venue_name", "venue_address")}),
        ("Contact", {"fields": ("instagram", "whatsapp", "phone")}),
    )

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class ScreeningInline(admin.TabularInline):
    model = Screening
    extra = 0
    fields = ("starts_at", "venue", "capacity", "status", "is_featured")
    show_change_link = True


@admin.register(Film)
class FilmAdmin(admin.ModelAdmin):
    list_display = ("poster_thumb", "title", "year", "director", "status", "on_ballot", "vote_total", "screened")
    list_display_links = ("poster_thumb", "title")
    list_filter = ("on_ballot", "status", "country")
    search_fields = ("title", "original_title", "director")
    list_editable = ("status", "on_ballot")
    readonly_fields = ("poster_preview", "suggested_by", "created_at")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [ScreeningInline]
    actions = ["put_on_ballot", "take_off_ballot", "reset_votes", "approve", "reject"]
    fieldsets = (
        (None, {"fields": ("title", "slug", "original_title", "year", "director", "country", "language", "runtime", "genres")}),
        ("Words", {"fields": ("tagline", "synopsis")}),
        ("Poster", {"fields": ("poster", "poster_url", "poster_preview", "palette", "trailer_url"),
                    "description": "Upload a poster or paste a URL. With neither, the site draws a typographic poster using the palette."}),
        ("Ballot", {"fields": ("status", "on_ballot", "suggested_by", "pitch", "created_at"),
                    "description": "Tick \"On the ballot\" to let members vote for this film. The ballot shows exactly the films ticked here."}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_votes=Count("votes", distinct=True), _shows=Count("screenings", distinct=True))

    @admin.display(description="", ordering=None)
    def poster_thumb(self, f):
        src = f.poster.url if f.poster else f.poster_url
        if src:
            return format_html('<img src="{}" style="width:34px;height:50px;object-fit:cover;border-radius:2px">', src)
        return mark_safe('<span style="display:inline-block;width:34px;height:50px;background:#1c2438;border-radius:2px"></span>')

    @admin.display(description="Preview")
    def poster_preview(self, f):
        src = f.poster.url if f.poster else f.poster_url
        return format_html('<img src="{}" style="max-width:220px">', src) if src else "No poster yet"

    @admin.action(description="Put on the ballot")
    def put_on_ballot(self, request, qs):
        n = qs.update(on_ballot=True, status="vault")
        self.message_user(request, f"{n} film(s) now on the ballot.")

    @admin.action(description="Take off the ballot")
    def take_off_ballot(self, request, qs):
        n = qs.update(on_ballot=False)
        self.message_user(request, f"{n} film(s) taken off the ballot.")

    @admin.action(description="Reset votes (start a fresh round)")
    def reset_votes(self, request, qs):
        n, _ = Vote.objects.filter(film__in=qs).delete()
        self.message_user(request, f"Cleared {n} vote(s).")

    @admin.display(description="Votes", ordering="_votes")
    def vote_total(self, f):
        return f._votes

    @admin.display(description="Screenings", ordering="_shows")
    def screened(self, f):
        return f._shows

    @admin.action(description="Move to the vault (approve suggestion)")
    def approve(self, request, qs):
        n = qs.update(status=Film.Status.VAULT)
        self.message_user(request, f"{n} film(s) now in the vault.", messages.SUCCESS)

    @admin.action(description="Mark as 'not this time'")
    def reject(self, request, qs):
        qs.update(status=Film.Status.REJECTED)


class ReservationInline(admin.TabularInline):
    model = Reservation
    extra = 0
    fields = ("user", "seats", "note", "attended", "created_at")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("user",)


@admin.register(Screening)
class ScreeningAdmin(admin.ModelAdmin):
    list_display = ("film", "starts_at", "venue", "status", "is_featured", "booked")
    list_filter = ("status", "is_featured")
    list_editable = ("status", "is_featured")
    date_hierarchy = "starts_at"
    autocomplete_fields = ("film",)
    inlines = [ReservationInline]
    actions = ["mark_done", "mark_cancelled"]

    @admin.display(description="Seats booked")
    def booked(self, s):
        taken = s.reservations.aggregate(t=Sum("seats"))["t"] or 0
        colour = "#e8572a" if taken >= s.capacity else "#5aa469"
        return format_html('<b style="color:{}">{}</b> / {}', colour, taken, s.capacity)

    @admin.action(description="Mark as screened (logs it for everyone marked attended)")
    def mark_done(self, request, qs):
        made = sum(s.mark_screened() for s in qs)
        self.message_user(request, f"Done. {made} logbook entries written.", messages.SUCCESS)

    @admin.action(description="Cancel screening")
    def mark_cancelled(self, request, qs):
        qs.update(status=Screening.Status.CANCELLED)


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ("code", "user", "screening", "seats", "attended", "created_at")
    list_filter = ("screening", "attended")
    list_editable = ("attended",)
    search_fields = ("user__username", "user__email")


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("user", "short", "target", "is_hidden", "created_at")
    list_filter = ("is_hidden",)
    list_editable = ("is_hidden",)
    search_fields = ("body", "user__username")
    actions = ["hide"]

    @admin.display(description="Comment")
    def short(self, c):
        return c.body[:80]

    @admin.display(description="On")
    def target(self, c):
        return c.film or c.screening

    @admin.action(description="Hide selected comments")
    def hide(self, request, qs):
        qs.update(is_hidden=True)
