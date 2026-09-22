from django.urls import path
from rest_framework.routers import SimpleRouter

from . import auth_views
from .admin_views import AdminUserViewSet
from .views import AddressViewSet

router = SimpleRouter()
router.register("addresses", AddressViewSet, basename="address")
router.register("admin/users", AdminUserViewSet, basename="admin-user")

urlpatterns = [
    path("auth/register/", auth_views.RegisterView.as_view(), name="auth-register"),
    path("auth/login/", auth_views.LoginView.as_view(), name="auth-login"),
    path("auth/logout/", auth_views.LogoutView.as_view(), name="auth-logout"),
    path("auth/token/refresh/", auth_views.RefreshView.as_view(), name="auth-token-refresh"),
    path("auth/password/forgot/", auth_views.ForgotPasswordView.as_view(), name="auth-password-forgot"),
    path("auth/password/reset/", auth_views.ResetPasswordView.as_view(), name="auth-password-reset"),
    path("auth/password/change/", auth_views.ChangePasswordView.as_view(), name="auth-password-change"),
    path("auth/me/", auth_views.MeView.as_view(), name="auth-me"),
    path("profile/", auth_views.ProfileView.as_view(), name="profile"),
    path("profile/avatar/", auth_views.AvatarView.as_view(), name="profile-avatar"),
    path("profile/deactivate/", auth_views.DeactivateAccountView.as_view(), name="profile-deactivate"),
    *router.urls,
]
