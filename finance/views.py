from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.audit import log_action
from core.decorators import perm_required
from core.http import form_errors, is_ajax, json_error, json_ok
from core.pagination import page_size_for
from core.permissions import FINANCE_MANAGE

from .forms import ExpenseForm, ReconcileForm
from .models import CashReconciliation, Expense, ExpenseCategory
from .services import expected_cash


def _paginate(request, queryset, section="default"):
    return Paginator(queryset, page_size_for(section)).get_page(request.GET.get("page"))


@perm_required(FINANCE_MANAGE)
def expenses(request):
    editing = None
    if request.GET.get("edit"):
        editing = get_object_or_404(Expense, pk=request.GET["edit"])
    form = ExpenseForm(
        instance=editing, initial=None if editing else {"date": timezone.localdate()}
    )
    if request.method == "POST":
        if request.POST.get("action") == "delete":
            expense = get_object_or_404(Expense, pk=request.POST.get("id"))
            description = expense.description
            expense.delete()
            log_action(action="Expense deleted", user=request.user, detail={"description": description}, request=request)
            if is_ajax(request):
                return json_ok("Expense deleted.", refresh_list=True)
            messages.success(request, "Expense deleted.")
            return redirect(request.path)
        instance = None
        if request.POST.get("id"):
            instance = get_object_or_404(Expense, pk=request.POST["id"])
        form = ExpenseForm(request.POST, instance=instance)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.user = request.user
            if expense.payment_method and not expense.method_name:
                expense.method_name = expense.payment_method.name
            expense.save()
            log_action(action="Expense saved", user=request.user, target=expense, request=request)
            if is_ajax(request):
                return json_ok(
                    "Expense saved.",
                    refresh_list=True,
                    redirect="" if instance is None else request.path,
                )
            messages.success(request, "Expense saved.")
            return redirect(request.path)
        if is_ajax(request):
            return json_error(errors=form_errors(form))
    queryset = Expense.objects.select_related("category", "payment_method", "user")
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    start = request.GET.get("start", "").strip()
    end = request.GET.get("end", "").strip()
    if query:
        queryset = queryset.filter(Q(description__icontains=query) | Q(reference__icontains=query))
    if category:
        queryset = queryset.filter(category_id=category)
    for raw, lookup in ((start, "date__gte"), (end, "date__lte")):
        if raw:
            try:
                queryset = queryset.filter(**{lookup: datetime.strptime(raw, "%Y-%m-%d").date()})
            except ValueError:
                pass
    page = _paginate(request, queryset, "expenses")
    total = queryset.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    context = {
        "form": form,
        "editing": editing,
        "page": page,
        "expenses": page,
        "categories": ExpenseCategory.objects.all(),
        "filters": {"q": query, "category": category, "start": start, "end": end},
        "list_url": request.path,
        "period_total": total,
    }
    fragment = request.GET.get("fragment")
    if fragment == "list":
        return render(request, "finance/_expense_list.html", context)
    if fragment == "form":
        return render(request, "finance/_expense_form.html", context)
    return render(request, "finance/expenses.html", context)


@perm_required(FINANCE_MANAGE)
def cash(request):
    today = timezone.localdate()
    day = today
    raw_day = request.GET.get("date", "").strip()
    if raw_day:
        try:
            day = datetime.strptime(raw_day, "%Y-%m-%d").date()
        except ValueError:
            day = today
    opening = (
        CashReconciliation.objects.filter(date=day).values_list("opening_float", flat=True).first()
        or Decimal("0")
    )
    form = ReconcileForm(
        initial={
            "date": day,
            "opening_float": opening,
            "counted_cash": opening,
        }
    )
    if request.method == "POST":
        form = ReconcileForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            expected = expected_cash(data["date"], data["opening_float"])
            difference = data["counted_cash"] - expected
            reconciliation, _ = CashReconciliation.objects.update_or_create(
                date=data["date"],
                defaults={
                    "opening_float": data["opening_float"],
                    "counted_cash": data["counted_cash"],
                    "expected_cash": expected,
                    "difference": difference,
                    "notes": data["notes"],
                    "user": request.user,
                },
            )
            log_action(
                action="Cash reconciled",
                user=request.user,
                target=reconciliation,
                detail={"expected": str(expected), "counted": str(data["counted_cash"])},
                request=request,
            )
            messages.success(request, f"Cash reconciliation saved for {data['date']}.")
            return redirect(f"{request.path}?date={data['date']}")
        messages.error(request, "Please correct the reconciliation details.")
    expected = expected_cash(day, opening)
    history = CashReconciliation.objects.all()[:30]
    return render(
        request,
        "finance/cash.html",
        {
            "form": form,
            "day": day,
            "expected": expected,
            "history": history,
        },
    )
