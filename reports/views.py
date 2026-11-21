from django.http import Http404
from django.shortcuts import render

from core.decorators import perm_required
from core.models import ShopSettings
from core.permissions import REPORTS_VIEW

from .exports import report_response
from .services import REPORTS, build_report, shop_date_range


@perm_required(REPORTS_VIEW)
def hub(request):
    cards = [
        {"slug": slug, "title": build_title, "description": description}
        for slug, (_, description) in REPORTS.items()
        for build_title in [slug.replace("_", " ").title()]
    ]
    return render(request, "reports/hub.html", {"cards": cards})


@perm_required(REPORTS_VIEW)
def view_report(request, slug):
    if slug not in REPORTS:
        raise Http404("Report not found")
    start, end = shop_date_range(request.GET)
    report = build_report(slug, start, end)
    fmt = request.GET.get("export")
    if fmt in {"csv", "xlsx", "pdf"}:
        return report_response(report, fmt, ShopSettings.load())
    return render(request, "reports/report.html", {"report": report, "cards": REPORTS})
