from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("ingest/posts/", views.ingest_posts, name="ingest_posts"),
]
