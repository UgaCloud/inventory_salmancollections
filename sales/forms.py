from decimal import Decimal

from django import forms

from core.forms import StyledForm, StyledModelForm
from core.models import PaymentMethod

from .models import Customer


class CustomerForm(StyledModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "email", "address", "notes", "is_active"]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class MixtureForm(StyledForm):
    name = forms.CharField(max_length=150, label="Mixture name")
    price = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2, label="Selling price")
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class MixtureSaleForm(StyledForm):
    method = forms.ModelChoiceField(
        queryset=PaymentMethod.objects.filter(is_active=True), label="Payment method"
    )
    amount = forms.DecimalField(
        min_value=Decimal("0.01"), decimal_places=2, label="Amount received"
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.filter(is_active=True),
        required=False,
        label="Customer",
        empty_label="Walk-in customer",
    )
    note = forms.CharField(required=False, max_length=200)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active = PaymentMethod.objects.filter(is_active=True)
        self.fields["method"].queryset = active
        self.fields["method"].initial = (
            active.filter(is_default=True).first() or active.first()
        )
        self.fields["customer"].queryset = Customer.objects.filter(
            is_active=True
        ).order_by("name")


class CustomerPaymentForm(StyledForm):
    amount = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2)
    method = forms.ModelChoiceField(queryset=PaymentMethod.objects.filter(is_active=True))
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    note = forms.CharField(required=False, max_length=200)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["method"].queryset = PaymentMethod.objects.filter(is_active=True)
        self.fields["method"].initial = (
            PaymentMethod.objects.filter(is_active=True, is_default=True).first()
        )
