from .logging import request_id_var
from .models import AuditLog


def _client_ip(request) -> str | None:
    """The client address as the throttles see it: X-Forwarded-For is trusted only for the
    `TRUSTED_PROXY_COUNT` proxies in front of the app (its right-most entries), never as sent."""
    if request is None:
        return None
    from django.conf import settings

    proxies = settings.REST_FRAMEWORK.get("NUM_PROXIES") or 0
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if proxies and forwarded:
        addresses = [a.strip() for a in forwarded.split(",") if a.strip()]
        if addresses:
            return addresses[-min(proxies, len(addresses))][:45]
    return request.META.get("REMOTE_ADDR")


def record_audit(*, action: str, actor=None, target=None, changes: dict | None = None, request=None) -> AuditLog:
    """Write an audit entry. Call from service-layer code for admin/sensitive mutations."""
    actor = actor if actor is not None and getattr(actor, "is_authenticated", False) else None
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        target_type=target._meta.label_lower if target is not None else "",
        target_id=str(target.pk) if target is not None else "",
        changes=changes or {},
        ip_address=_client_ip(request),
        request_id=request_id_var.get(),
    )
