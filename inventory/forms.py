from decimal import Decimal, InvalidOperation

from django import forms

from core.forms import StyledForm, StyledModelForm
from core.models import ShopSettings

from .models import Category, Product, Supplier, Unit


class UnitForm(StyledModelForm):
    class Meta:
        model = Unit
        fields = ["name", "code", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].help_text = (
            "Short code stored on products (max 10 characters, no spaces). "
            "It cannot be changed while products use this unit."
        )

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip().lower()
        if not code:
            raise forms.ValidationError("Enter the short code for this unit.")
        if " " in code:
            raise forms.ValidationError("The code cannot contain spaces.")
        if self.instance and self.instance.pk and self.instance.code != code:
            if Product.objects.filter(unit=self.instance.code).exists():
                raise forms.ValidationError(
                    "This unit is used by existing products, so its code cannot change. "
                    "Create a new unit instead."
                )
        return code

    def clean_name(self):
        return (self.cleaned_data.get("name") or "").strip()


class CategoryForm(StyledModelForm):
    class Meta:
        model = Category
        fields = ["name", "description", "is_active"]

    def clean_name(self):
        return (self.cleaned_data.get("name") or "").strip()


class SupplierForm(StyledModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_person", "phone", "email", "address", "notes", "is_active"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2}), "notes": forms.Textarea(attrs={"rows": 2})}


class ProductForm(StyledModelForm):
    preset_sizes_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "5:2.50\n10:4.50\n15:6.50"}),
        label="Preset selling sizes",
        help_text="Bulk perfumes only. One size per line as millilitres:price, e.g. 10:4.50.",
    )
    opening_stock = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        initial=0,
        label="Opening stock",
        help_text="Applied only when the product is created.",
    )
    opening_cost = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        initial=0,
        decimal_places=4,
        label="Opening cost per unit",
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "sku",
            "barcode",
            "category",
            "kind",
            "unit",
            "brand",
            "concentration",
            "description",
            "image",
            "unit_price",
            "reorder_level",
            "is_active",
            "bulk_parent",
            "packed_size_ml",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "packed_size_ml": forms.NumberInput(attrs={"step": "0.001"}),
            "reorder_level": forms.NumberInput(attrs={"step": "0.001"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bulk_parent"].queryset = Product.objects.filter(
            kind=Product.KIND_BULK, is_active=True
        ).order_by("name")
        self.fields["bulk_parent"].help_text = "Packed bottles only: the bulk perfume it belongs to."
        self.fields["category"].queryset = Category.objects.filter(is_active=True)
        current_unit = self.instance.unit if self.instance and self.instance.pk else None
        units = Unit.objects.filter(is_active=True)
        if current_unit:
            units = Unit.objects.filter(code=current_unit) | units
        self.fields["unit"].choices = [
            (unit.code, f"{unit.name} ({unit.code})") for unit in units.distinct().order_by("name")
        ] or list(Product.UNIT_CHOICES)
        if current_unit and self.instance.category_id:
            self.fields["category"].queryset = Category.objects.filter(is_active=True) | Category.objects.filter(
                pk=self.instance.category_id
            )
        if self.instance and self.instance.pk:
            self.fields["preset_sizes_text"].initial = "\n".join(
                f"{item.get('ml')}:{item.get('price')}"
                for item in (self.instance.preset_sizes or [])
            )
            self.fields["opening_stock"].disabled = True
            self.fields["opening_cost"].disabled = True
        else:
            self.fields["reorder_level"].initial = ShopSettings.load().low_stock_threshold
            self.fields["preset_sizes_text"].initial = "5:2.50\n10:4.50\n15:6.50"

    def clean_barcode(self):
        barcode = (self.cleaned_data.get("barcode") or "").strip()
        return barcode or None

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        if kind == Product.KIND_BULK:
            cleaned["unit"] = Product.UNIT_ML
            cleaned["bulk_parent"] = None
            cleaned["packed_size_ml"] = None
        elif kind == Product.KIND_PACKED:
            if not cleaned.get("unit") or cleaned.get("unit") == Product.UNIT_ML:
                cleaned["unit"] = Product.UNIT_BOTTLE
        else:
            cleaned["bulk_parent"] = None
            cleaned["packed_size_ml"] = None
            if cleaned.get("unit") == Product.UNIT_ML:
                cleaned["unit"] = Product.UNIT_PIECE

        presets = []
        if kind == Product.KIND_BULK:
            raw = (cleaned.get("preset_sizes_text") or "").strip()
            seen = set()
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                separator = ":" if ":" in line else None
                parts = line.split(separator) if separator else []
                if len(parts) != 2:
                    self.add_error("preset_sizes_text", f"'{line}' should look like 10:4.50")
                    continue
                try:
                    ml = Decimal(parts[0].strip())
                    price = Decimal(parts[1].strip())
                except InvalidOperation:
                    self.add_error("preset_sizes_text", f"'{line}' contains an invalid number.")
                    continue
                if ml <= 0 or price < 0:
                    self.add_error("preset_sizes_text", f"'{line}' must have a positive size and a valid price.")
                    continue
                if ml in seen:
                    self.add_error("preset_sizes_text", f"Size {ml}ml is listed twice.")
                    continue
                seen.add(ml)
                presets.append({"ml": str(ml), "price": str(price.quantize(Decimal("0.01")))})
            presets.sort(key=lambda item: Decimal(item["ml"]))
        self.instance.preset_sizes = presets
        return cleaned

    def save(self, commit=True):
        product = super().save(commit=False)
        product.preset_sizes = self.instance.preset_sizes
        if not product.barcode:
            product.barcode = None
        if commit:
            product.save()
            self.save_m2m()
        return product


class PurchaseForm(StyledForm):
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.filter(is_active=True), required=True)
    purchase_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    reference = forms.CharField(required=False, max_length=80)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True).order_by("name")


class StockAdjustForm(StyledForm):
    product = forms.ModelChoiceField(queryset=Product.objects.filter(is_active=True))
    direction = forms.ChoiceField(
        choices=[("increase", "Add stock"), ("decrease", "Remove stock")], initial="increase"
    )
    quantity = forms.DecimalField(min_value=Decimal("0.001"), decimal_places=3)
    reason = forms.ChoiceField(choices=[])
    note = forms.CharField(required=False, max_length=200)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import StockAdjustment

        self.fields["reason"].choices = StockAdjustment.REASON_CHOICES
        self.fields["product"].queryset = Product.objects.filter(is_active=True).order_by("name")


class PackForm(StyledForm):
    bulk_product = forms.ModelChoiceField(
        queryset=Product.objects.filter(kind=Product.KIND_BULK, is_active=True)
    )
    packed_product = forms.ModelChoiceField(
        queryset=Product.objects.filter(kind=Product.KIND_PACKED, is_active=True)
    )
    ml_per_bottle = forms.DecimalField(min_value=Decimal("0.001"), decimal_places=3, label="Millilitres per bottle")
    bottles = forms.IntegerField(min_value=1, label="Bottles to produce")
    extra_cost_per_bottle = forms.DecimalField(
        required=False, min_value=Decimal("0"), decimal_places=2, initial=0,
        label="Extra cost per bottle (optional)",
        help_text="Bottle, cap and label cost if it is not already in the liquid cost.",
    )
    note = forms.CharField(required=False, max_length=200)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bulk_product"].queryset = Product.objects.filter(
            kind=Product.KIND_BULK, is_active=True
        ).order_by("name")
        self.fields["packed_product"].queryset = Product.objects.filter(
            kind=Product.KIND_PACKED, is_active=True
        ).select_related("bulk_parent").order_by("name")


class ImportForm(StyledForm):
    file = forms.FileField(
        help_text="CSV file. Download the template below to see the required columns."
    )
