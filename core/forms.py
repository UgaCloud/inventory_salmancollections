from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import PaymentMethod, Role, ShopSettings
from .permissions import PERMISSION_GROUPS

INPUT_CLASS = "w-full field-control"
CHECK_CLASS = (
    "h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
)


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", CHECK_CLASS)
            elif isinstance(widget, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                widget.attrs.setdefault("class", "space-y-1")
            else:
                widget.attrs.setdefault("class", INPUT_CLASS)
            if field.required and not isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("required", "required")


class StyledModelForm(StyledFormMixin, forms.ModelForm):
    pass


class StyledForm(StyledFormMixin, forms.Form):
    pass


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = INPUT_CLASS
        self.fields["username"].widget.attrs["autofocus"] = "autofocus"
        self.fields["username"].label = "Username"
        self.fields["password"].label = "Password"


class BusinessSettingsForm(StyledModelForm):
    class Meta:
        model = ShopSettings
        fields = [
            "name",
            "currency_code",
            "currency_symbol",
            "phone",
            "email",
            "address",
            "logo",
            "receipt_header",
            "receipt_footer",
            "receipt_show_logo",
            "allow_partial_payments",
            "low_stock_threshold",
            "auto_backup_enabled",
            "backup_retention",
        ]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "receipt_footer": forms.Textarea(attrs={"rows": 3}),
        }


class PaginationForm(StyledModelForm):
    class Meta:
        model = ShopSettings
        fields = [
            "page_size_default",
            "page_size_products",
            "page_size_stock",
            "page_size_purchases",
            "page_size_sales",
            "page_size_customers",
            "page_size_payments",
            "page_size_expenses",
            "page_size_audit",
            "page_size_pos",
        ]
        help_texts = {
            "page_size_default": "Used by any table that has no size of its own.",
            "page_size_products": "Rows per page in the product and perfume workspaces.",
            "page_size_pos": "Product cards shown per page in the point of sale catalogue.",
        }

    def clean_page_size_default(self):
        return max(5, min(100, self.cleaned_data["page_size_default"]))


class PaymentMethodForm(StyledModelForm):
    class Meta:
        model = PaymentMethod
        fields = ["name", "kind", "is_active", "is_default", "sort_order"]


class StaffUserForm(StyledForm):
    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=40, required=False)
    role = forms.ModelChoiceField(queryset=Role.objects.all(), required=True)
    is_active = forms.BooleanField(required=False, initial=True)
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Leave blank when editing to keep the current password.",
    )

    def __init__(self, *args, profile=None, **kwargs):
        self.profile = profile
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = Role.objects.all()
        if profile:
            self.fields["username"].initial = profile.user.username
            self.fields["first_name"].initial = profile.user.first_name
            self.fields["last_name"].initial = profile.user.last_name
            self.fields["email"].initial = profile.user.email
            self.fields["phone"].initial = profile.phone
            self.fields["role"].initial = profile.role
            self.fields["is_active"].initial = profile.is_active
            self.fields["username"].disabled = True
        else:
            self.fields["password"].required = True

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        qs = User.objects.filter(username__iexact=username)
        if self.profile:
            qs = qs.exclude(pk=self.profile.user_id)
        if qs.exists():
            raise ValidationError("That username is already in use.")
        return username

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            validate_password(password)
        return password

    def save(self):
        data = self.cleaned_data
        if self.profile:
            user = self.profile.user
            profile = self.profile
        else:
            user = User(username=data["username"])
            profile = None
        user.first_name = data["first_name"]
        user.last_name = data["last_name"]
        user.email = data["email"]
        user.is_active = data["is_active"]
        if data["password"]:
            user.set_password(data["password"])
        user.save()
        from .models import StaffProfile

        if profile is None:
            profile, _ = StaffProfile.objects.get_or_create(user=user)
        profile.role = data["role"]
        profile.phone = data["phone"]
        profile.is_active = data["is_active"]
        profile.save()
        return profile


class RoleForm(StyledModelForm):
    permissions = forms.MultipleChoiceField(
        choices=[(code, label) for _, items in PERMISSION_GROUPS for code, label in items],
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = Role
        fields = ["name", "dashboard", "permissions"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["dashboard"].required = False
        self.fields["dashboard"].empty_label = "Automatic (match the role)"
        self.fields["dashboard"].help_text = (
            "Which dashboard this role sees. Dashboard assignment is separate from "
            "module permissions and never grants access to restricted data."
        )
        if self.instance and self.instance.pk:
            self.fields["permissions"].initial = self.instance.permissions or []
        self.grouped_permissions = PERMISSION_GROUPS

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs = Role.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("A role with that name already exists.")
        return name
