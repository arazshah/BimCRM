from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Membership, User


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["tenant"]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-date_joined",)
    list_display = ("mobile", "full_name", "is_staff", "is_active", "date_joined")
    search_fields = ("mobile", "full_name")
    list_filter = ("is_staff", "is_active")
    inlines = [MembershipInline]
    fieldsets = (
        (None, {"fields": ("mobile", "full_name", "password")}),
        ("دسترسی", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("تاریخ‌ها", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("mobile", "full_name", "password1", "password2")}),)
