from django.http import JsonResponse


def is_ajax(request) -> bool:
    return (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in request.headers.get("accept", "")
        and request.method != "GET"
    )


def wants_fragment(request) -> str:
    return request.GET.get("fragment", "")


def form_errors(form) -> dict:
    errors = {}
    for field, messages in form.errors.items():
        key = field if field != "__all__" else "_form"
        errors[key] = [str(m) for m in messages]
    return errors


def json_ok(message="", **extra):
    payload = {"ok": True, "message": message}
    payload.update(extra)
    return JsonResponse(payload)


def json_error(message="Please correct the highlighted fields.", errors=None, status=400, **extra):
    payload = {"ok": False, "message": message, "errors": errors or {}}
    payload.update(extra)
    return JsonResponse(payload, status=status)
