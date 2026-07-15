from django.urls import path

from . import views

app_name = "survey"

urlpatterns = [
    path("", views.home, name="home"),
    path("kiosk/<int:kiosk_id>/", views.kiosk_page, name="kiosk"),
    path("kiosk/<int:kiosk_id>/qr", views.kiosk_qr, name="kiosk_qr"),
    path("s/<str:token>", views.scan, name="scan"),
    path("survey/<uuid:session_id>/start", views.start, name="start"),
    path("survey/<uuid:session_id>/q/<int:step>", views.question, name="question"),
    path("survey/<uuid:session_id>/claim", views.claim, name="claim"),
    path("claim/verify/<str:token>", views.verify, name="verify"),
]
