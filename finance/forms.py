from django import forms

from core.forms import StyledForm, StyledModelForm
from core.models import PaymentMethod

from .models import Expense, ExpenseCategory


class ExpenseForm(StyledModelForm):
    class Meta:
        model = Expense
        fields = ["date", "category", "amount", "payment_method", "description", "reference"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = ExpenseCategory.objects.all()
        self.fields["payment_method"].queryset = PaymentMethod.objects.filter(is_active=True)
        self.fields["payment_method"].initial = (
            PaymentMethod.objects.filter(is_active=True, is_default=True).first()
        )


class ReconcileForm(StyledForm):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    opening_float = forms.DecimalField(min_value=0, decimal_places=2, initial=0)
    counted_cash = forms.DecimalField(min_value=0, decimal_places=2, initial=0)
    notes = forms.CharField(required=False, max_length=200, widget=forms.Textarea(attrs={"rows": 2}))
