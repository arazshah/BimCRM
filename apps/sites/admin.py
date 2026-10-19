from django.contrib import admin

from .models import SiteLineContent, SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ("tenant", "template", "is_published", "updated_at")
    list_filter = ("template", "is_published")
    search_fields = ("tenant__slug", "tenant__name")

    def get_queryset(self, request):
        return SiteSettings.all_objects.select_related("tenant")


@admin.register(SiteLineContent)
class SiteLineContentAdmin(admin.ModelAdmin):
    list_display = ("tenant", "line", "updated_at")
    list_filter = ("line",)
    search_fields = ("tenant__slug", "tenant__name", "line__name")

    def get_queryset(self, request):
        return SiteLineContent.all_objects.select_related("tenant", "line")
