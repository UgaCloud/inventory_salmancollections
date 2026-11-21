from .models import AuditLog


def log_action(*, action, user=None, target=None, detail=None, request=None):
    """Record a sensitive activity in the audit trail."""
    target_type = ""
    target_id = ""
    if target is not None:
        target_type = target.__class__.__name__
        target_id = str(target.pk)
    ip = None
    if request is not None:
        ip = request.META.get("REMOTE_ADDR") or None
    return AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail or {},
        ip_address=ip,
    )
