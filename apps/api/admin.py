from django.contrib import admin

from .models import IngestRecord, IngestToken


@admin.register(IngestToken)
class IngestTokenAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "is_active", "created_at", "last_used_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "workspace__name")
    readonly_fields = ("token_hash", "created_at", "last_used_at")


@admin.register(IngestRecord)
class IngestRecordAdmin(admin.ModelAdmin):
    list_display = ("external_ref", "workspace", "post", "source", "created_at")
    list_filter = ("source", "created_at")
    search_fields = ("external_ref",)
    readonly_fields = ("created_at", "updated_at")
