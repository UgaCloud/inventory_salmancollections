from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import PaymentMethod, Role, ShopSettings, StaffProfile
from core.services import ensure_defaults
from finance.models import CashReconciliation, Expense, ExpenseCategory
from finance.services import expected_cash
from inventory.models import (
    Category,
    PackRun,
    Product,
    Purchase,
    StockAdjustment,
    Supplier,
)
from inventory.services import (
    add_opening_stock,
    adjust_stock,
    pack_from_bulk,
    receive_purchase,
)
from sales.models import Customer, CustomerPayment, Mixture, Sale
from sales.services import cancel_sale, checkout, prepare_mixture, record_customer_payment

DEMO_STAFF = [
    ("manager", "Maya", "Manager", "manager", "manager12345"),
    ("cashier", "Chris", "Cashier", "cashier", "cashier12345"),
    ("storekeeper", "Sam", "Store", "storekeeper", "store12345"),
    ("accountant", "Ada", "Accounts", "accountant", "account12345"),
]

DEMO_CUSTOMERS = [
    ("Amina Yusuf", "+254 700 000 001", "amina@example.com"),
    ("Brian Otieno", "+254 700 000 002", ""),
    ("Fatuma Ali", "+254 700 000 003", "fatuma@example.com"),
    ("Grace Wanjiku", "+254 700 000 004", ""),
    ("Daniel Kim", "+254 700 000 005", "daniel@example.com"),
    ("Sarah Mwangi", "+254 700 000 006", ""),
    ("Peter Njoroge", "+254 700 000 007", ""),
    ("Halima Abdi", "+254 700 000 008", "halima@example.com"),
    ("Kevin Ouma", "+254 700 000 009", ""),
    ("Lucy Achieng", "+254 700 000 010", ""),
]

DEMO_SALE_NOTE = "Demo sale"


class Command(BaseCommand):
    help = (
        "Create the shop settings, default roles, payment methods and expense "
        "categories, plus a complete demo catalogue and transaction history."
    )

    def add_arguments(self, parser):
        parser.add_argument("--no-demo", action="store_true", help="Skip all demo data and staff.")
        parser.add_argument(
            "--no-transactions",
            action="store_true",
            help="Create the catalogue only, without purchases, sales and expenses.",
        )
        parser.add_argument("--owner-password", default="owner12345")
        parser.add_argument("--owner-username", default="owner")

    def handle(self, *args, **options):
        ensure_defaults()
        shop = ShopSettings.load()
        if shop.name in ("My Boutique", ""):
            shop.name = "Amber & Co. Boutique"
            shop.receipt_header = "Perfumes & lifestyle boutique"
            shop.save()

        roles = {role.slug: role for role in Role.objects.all()}
        owner, created = User.objects.get_or_create(
            username=options["owner_username"],
            defaults={
                "first_name": "Shop",
                "last_name": "Owner",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            owner.set_password(options["owner_password"])
            owner.save()
        profile, _ = StaffProfile.objects.get_or_create(user=owner)
        profile.role = roles["owner"]
        profile.is_active = True
        profile.save()

        if not options["no_demo"]:
            for username, first, last, role_slug, password in DEMO_STAFF:
                user, user_created = User.objects.get_or_create(
                    username=username,
                    defaults={"first_name": first, "last_name": last},
                )
                if user_created:
                    user.set_password(password)
                    user.save()
                staff_profile, _ = StaffProfile.objects.get_or_create(user=user)
                staff_profile.role = roles[role_slug]
                staff_profile.is_active = True
                staff_profile.save()
            products = self._demo_catalogue(owner)
            if not options["no_transactions"]:
                self._demo_transactions(products, owner)

        self.stdout.write(self.style.SUCCESS("Shop is ready."))
        self.stdout.write(f"  Settings : {shop.name}")
        self.stdout.write(f"  Owner    : {options['owner_username']} / {options['owner_password']}")
        if not options["no_demo"]:
            for username, _, _, _, password in DEMO_STAFF:
                self.stdout.write(f"  Staff    : {username} / {password}")
            self.stdout.write(
                f"  Data     : {Product.objects.count()} products · "
                f"{Sale.objects.count()} sales · {Customer.objects.count()} customers"
            )
        self.stdout.write("  Run: python manage.py runserver")

    # ------------------------------------------------------------------
    # Catalogue
    # ------------------------------------------------------------------
    def _demo_catalogue(self, owner):
        categories = {
            name: Category.objects.get_or_create(name=name)[0]
            for name in ["Perfumes", "Bags", "Shoes", "Accessories", "Skincare"]
        }
        supplier, _ = Supplier.objects.get_or_create(
            name="Dubai Fragrance Trading",
            defaults={
                "contact_person": "Khalid",
                "phone": "+971 50 000 0000",
                "email": "orders@example.com",
                "address": "Deira, Dubai",
            },
        )
        Supplier.objects.get_or_create(
            name="Nairobi Leather Works",
            defaults={
                "contact_person": "Wanjiru",
                "phone": "+254 711 000 100",
                "email": "sales@leatherworks.example",
                "address": "Industrial Area, Nairobi",
            },
        )
        Supplier.objects.get_or_create(
            name="Amber House Distribution",
            defaults={
                "contact_person": "Yusuf",
                "phone": "+254 711 000 200",
                "email": "orders@amberhouse.example",
                "address": "Mombasa Road, Nairobi",
            },
        )
        for name, phone, email in DEMO_CUSTOMERS:
            Customer.objects.get_or_create(
                name=name, defaults={"phone": phone, "email": email}
            )

        products = {}

        def create_product(**data):
            sku = data["sku"]
            opening = data.pop("opening", 0)
            cost = data.pop("cost", 0)
            product = Product.objects.filter(sku=sku).first()
            if product is None:
                product = Product.objects.create(**data)
                if opening:
                    add_opening_stock(product, opening, cost, user=owner)
            products[sku] = product
            return product

        create_product(
            name="Leather Tote Bag",
            sku="BAG-001",
            barcode="6001001001",
            category=categories["Bags"],
            kind=Product.KIND_STANDARD,
            unit=Product.UNIT_PIECE,
            unit_price=Decimal("45.00"),
            reorder_level=Decimal("3"),
            description="Everyday leather tote.",
            opening=Decimal("8"),
            cost=Decimal("22.00"),
        )
        create_product(
            name="Mini Crossbody Bag",
            sku="BAG-002",
            barcode="6001001002",
            category=categories["Bags"],
            kind=Product.KIND_STANDARD,
            unit=Product.UNIT_PIECE,
            unit_price=Decimal("38.00"),
            reorder_level=Decimal("3"),
            description="Compact crossbody in saffiano leather.",
            opening=Decimal("6"),
            cost=Decimal("17.00"),
        )
        create_product(
            name="Classic White Sneakers",
            sku="SHOE-001",
            barcode="6001002002",
            category=categories["Shoes"],
            kind=Product.KIND_STANDARD,
            unit=Product.UNIT_PAIR,
            unit_price=Decimal("60.00"),
            reorder_level=Decimal("2"),
            opening=Decimal("5"),
            cost=Decimal("30.00"),
        )
        create_product(
            name="Silk Scarf",
            sku="ACC-001",
            barcode="6001004004",
            category=categories["Accessories"],
            kind=Product.KIND_STANDARD,
            unit=Product.UNIT_PIECE,
            unit_price=Decimal("18.00"),
            reorder_level=Decimal("5"),
            opening=Decimal("12"),
            cost=Decimal("7.00"),
        )
        create_product(
            name="Gold Plated Watch",
            sku="ACC-002",
            barcode="6001004005",
            category=categories["Accessories"],
            kind=Product.KIND_STANDARD,
            unit=Product.UNIT_PIECE,
            unit_price=Decimal("95.00"),
            reorder_level=Decimal("2"),
            opening=Decimal("4"),
            cost=Decimal("48.00"),
        )
        create_product(
            name="Shea Body Lotion",
            sku="SKIN-001",
            barcode="6001005006",
            category=categories["Skincare"],
            kind=Product.KIND_STANDARD,
            unit=Product.UNIT_PIECE,
            unit_price=Decimal("12.50"),
            reorder_level=Decimal("6"),
            opening=Decimal("20"),
            cost=Decimal("5.00"),
        )

        oud = create_product(
            name="Oud Royale",
            sku="OUD-BULK",
            category=categories["Perfumes"],
            kind=Product.KIND_BULK,
            unit=Product.UNIT_ML,
            brand="House of Oud",
            concentration="EDP",
            description="Deep oud with amber and sandalwood.",
            unit_price=Decimal("1.20"),
            reorder_level=Decimal("100"),
            preset_sizes=[
                {"ml": "5", "price": "7.00"},
                {"ml": "10", "price": "12.00"},
                {"ml": "15", "price": "17.00"},
                {"ml": "30", "price": "32.00"},
            ],
            opening=Decimal("500"),
            cost=Decimal("0.55"),
        )
        create_product(
            name="Oud Royale 30ml",
            sku="OUD-30",
            barcode="6001003003",
            category=categories["Perfumes"],
            kind=Product.KIND_PACKED,
            unit=Product.UNIT_BOTTLE,
            brand="House of Oud",
            concentration="EDP",
            unit_price=Decimal("32.00"),
            reorder_level=Decimal("4"),
            bulk_parent=oud,
            packed_size_ml=Decimal("30"),
            opening=Decimal("12"),
            cost=Decimal("16.50"),
        )
        musk = create_product(
            name="White Musk",
            sku="MUSK-BULK",
            category=categories["Perfumes"],
            kind=Product.KIND_BULK,
            unit=Product.UNIT_ML,
            brand="Amber House",
            concentration="EDT",
            unit_price=Decimal("0.90"),
            reorder_level=Decimal("80"),
            preset_sizes=[
                {"ml": "5", "price": "5.50"},
                {"ml": "10", "price": "10.00"},
            ],
            opening=Decimal("300"),
            cost=Decimal("0.38"),
        )
        create_product(
            name="White Musk 30ml",
            sku="MUSK-30",
            barcode="6001003007",
            category=categories["Perfumes"],
            kind=Product.KIND_PACKED,
            unit=Product.UNIT_BOTTLE,
            brand="Amber House",
            concentration="EDT",
            unit_price=Decimal("22.00"),
            reorder_level=Decimal("4"),
            bulk_parent=musk,
            packed_size_ml=Decimal("30"),
            opening=Decimal("10"),
            cost=Decimal("11.40"),
        )
        rose = create_product(
            name="Rose Attar",
            sku="ROSE-BULK",
            category=categories["Perfumes"],
            kind=Product.KIND_BULK,
            unit=Product.UNIT_ML,
            brand="Amber House",
            concentration="Parfum",
            unit_price=Decimal("1.50"),
            reorder_level=Decimal("50"),
            preset_sizes=[
                {"ml": "3", "price": "5.00"},
                {"ml": "6", "price": "9.00"},
            ],
            opening=Decimal("200"),
            cost=Decimal("0.70"),
        )
        create_product(
            name="Rose Attar 10ml",
            sku="ROSE-10",
            barcode="6001003008",
            category=categories["Perfumes"],
            kind=Product.KIND_PACKED,
            unit=Product.UNIT_BOTTLE,
            brand="Amber House",
            concentration="Parfum",
            unit_price=Decimal("18.00"),
            reorder_level=Decimal("4"),
            bulk_parent=rose,
            packed_size_ml=Decimal("10"),
            opening=Decimal("8"),
            cost=Decimal("7.00"),
        )
        create_product(
            name="Amber Noir",
            sku="AMBER-BULK",
            category=categories["Perfumes"],
            kind=Product.KIND_BULK,
            unit=Product.UNIT_ML,
            brand="Amber House",
            concentration="EDP",
            description="Warm amber, vanilla and tonka.",
            unit_price=Decimal("1.40"),
            reorder_level=Decimal("60"),
            preset_sizes=[
                {"ml": "5", "price": "8.00"},
                {"ml": "10", "price": "14.00"},
                {"ml": "20", "price": "26.00"},
            ],
            opening=Decimal("300"),
            cost=Decimal("0.62"),
        )
        create_product(
            name="Jasmine Bloom",
            sku="JASMINE-BULK",
            category=categories["Perfumes"],
            kind=Product.KIND_BULK,
            unit=Product.UNIT_ML,
            brand="Amber House",
            concentration="EDT",
            description="Fresh jasmine with a soft citrus opening.",
            unit_price=Decimal("1.10"),
            reorder_level=Decimal("50"),
            preset_sizes=[
                {"ml": "5", "price": "6.50"},
                {"ml": "10", "price": "11.50"},
            ],
            opening=Decimal("250"),
            cost=Decimal("0.48"),
        )
        return products

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------
    def _demo_transactions(self, products, owner):
        if Sale.objects.filter(note__startswith=DEMO_SALE_NOTE).exists():
            self.stdout.write("  Demo transactions already exist; skipping.")
            return

        today = timezone.localdate()
        cashier = User.objects.filter(username="cashier").first() or owner
        by_kind = {method.kind: method for method in PaymentMethod.objects.all()}
        cash = by_kind.get("cash") or PaymentMethod.objects.first()
        card = by_kind.get("card") or cash
        mobile = by_kind.get("mobile") or cash
        customers = {customer.name: customer for customer in Customer.objects.all()}

        supplier = Supplier.objects.filter(name="Dubai Fragrance Trading").first()
        if supplier and not Purchase.objects.filter(reference="DEMO-PO-1").exists():
            receive_purchase(
                supplier=supplier,
                items=[
                    {"product": products["OUD-BULK"], "quantity": Decimal("400"), "unit_cost": Decimal("0.58")},
                    {"product": products["MUSK-BULK"], "quantity": Decimal("300"), "unit_cost": Decimal("0.40")},
                    {"product": products["BAG-001"], "quantity": Decimal("6"), "unit_cost": Decimal("21.00")},
                ],
                user=owner,
                purchase_date=today - timedelta(days=26),
                reference="DEMO-PO-1",
                note="Demo opening order",
            )
        if supplier and not Purchase.objects.filter(reference="DEMO-PO-2").exists():
            receive_purchase(
                supplier=supplier,
                items=[
                    {"product": products["ROSE-BULK"], "quantity": Decimal("150"), "unit_cost": Decimal("0.72")},
                    {"product": products["JASMINE-BULK"], "quantity": Decimal("120"), "unit_cost": Decimal("0.50")},
                ],
                user=owner,
                purchase_date=today - timedelta(days=12),
                reference="DEMO-PO-2",
                note="Demo restock",
            )

        if not PackRun.objects.filter(note="Demo packing run").exists():
            pack_from_bulk(
                bulk_product=products["OUD-BULK"],
                packed_product=products["OUD-30"],
                ml_per_bottle=Decimal("30"),
                bottles=4,
                user=owner,
                note="Demo packing run",
                extra_cost_per_bottle=Decimal("0.75"),
            )

        amber_rose = Mixture.objects.filter(name="Amber Rose Blend").first()
        if amber_rose is None:
            amber_rose = prepare_mixture(
                name="Amber Rose Blend",
                components=[
                    {"product": products["OUD-BULK"], "quantity_ml": Decimal("10")},
                    {"product": products["ROSE-BULK"], "quantity_ml": Decimal("5")},
                ],
                price=Decimal("38.00"),
                user=owner,
                notes="Demo blend of oud and rose.",
            )
        desert_musk = Mixture.objects.filter(name="Desert Musk").first()
        if desert_musk is None:
            desert_musk = prepare_mixture(
                name="Desert Musk",
                components=[
                    {"product": products["MUSK-BULK"], "quantity_ml": Decimal("8")},
                    {"product": products["AMBER-BULK"], "quantity_ml": Decimal("4")},
                ],
                price=Decimal("22.00"),
                user=owner,
                notes="Demo soft musk blend.",
            )

        def record_sale(label, lines, method, *, customer=None, amount=None, discount=Decimal("0"), days_ago=0, cancel=False):
            items = [
                {"product_id": product.pk, "quantity": quantity}
                for product, quantity in lines
            ]
            subtotal = sum(
                (product.price_for_quantity(quantity) for product, quantity in lines),
                Decimal("0"),
            )
            if amount is None:
                amount = subtotal - discount + (Decimal("5") if customer is None else Decimal("0"))
            sale, _change = checkout(
                items=items,
                payments=[{"method": method, "amount": amount}],
                cashier=cashier,
                customer=customer,
                discount=discount,
                note=f"{DEMO_SALE_NOTE} · {label}",
            )
            if days_ago:
                Sale.objects.filter(pk=sale.pk).update(
                    created_at=timezone.now() - timedelta(days=days_ago)
                )
            if cancel:
                cancel_sale(sale=sale, user=owner, reason="Demo return")
            return sale

        def record_mixture_sale(label, mixture, method, days_ago=0):
            sale, _change = checkout(
                items=[{"mixture_id": mixture.pk}],
                payments=[{"method": method, "amount": mixture.price}],
                cashier=cashier,
                note=f"{DEMO_SALE_NOTE} · {label}",
            )
            if days_ago:
                Sale.objects.filter(pk=sale.pk).update(
                    created_at=timezone.now() - timedelta(days=days_ago)
                )
            return sale

        amina = customers.get("Amina Yusuf")
        brian = customers.get("Brian Otieno")

        record_sale(
            "Tote and oud",
            [(products["BAG-001"], Decimal("1")), (products["OUD-BULK"], Decimal("12"))],
            card,
            days_ago=0,
        )
        record_sale(
            "Packed oud bottle",
            [(products["OUD-30"], Decimal("1"))],
            cash,
            days_ago=1,
        )
        record_sale(
            "Sneakers and rose",
            [(products["SHOE-001"], Decimal("1")), (products["ROSE-BULK"], Decimal("6"))],
            mobile,
            customer=amina,
            days_ago=2,
        )
        record_mixture_sale("Amber Rose mixture", amber_rose, cash, days_ago=3)
        record_sale(
            "Watch for Brian",
            [(products["ACC-002"], Decimal("1"))],
            card,
            customer=brian,
            days_ago=4,
        )
        record_sale(
            "Scarf and lotion",
            [(products["ACC-001"], Decimal("1")), (products["SKIN-001"], Decimal("1"))],
            cash,
            days_ago=5,
        )
        record_sale(
            "Crossbody on credit",
            [(products["BAG-002"], Decimal("1"))],
            cash,
            customer=amina,
            amount=Decimal("20.00"),
            days_ago=6,
        )
        record_sale(
            "Oud 25ml",
            [(products["OUD-BULK"], Decimal("25"))],
            cash,
            days_ago=7,
        )
        record_sale(
            "Musk bulk and bottle",
            [(products["MUSK-BULK"], Decimal("30")), (products["MUSK-30"], Decimal("1"))],
            card,
            days_ago=8,
        )
        record_mixture_sale("Desert Musk mixture", desert_musk, cash, days_ago=9)
        record_sale(
            "Returned tote",
            [(products["BAG-001"], Decimal("1")), (products["OUD-BULK"], Decimal("5"))],
            cash,
            days_ago=10,
            cancel=True,
        )
        record_sale(
            "Sneakers restock sale",
            [(products["SHOE-001"], Decimal("1"))],
            cash,
            days_ago=11,
        )
        record_sale(
            "Rose 10ml",
            [(products["ROSE-10"], Decimal("1"))],
            card,
            days_ago=12,
        )
        record_sale(
            "Gift set",
            [(products["ACC-002"], Decimal("1")), (products["ACC-001"], Decimal("1"))],
            cash,
            days_ago=14,
        )
        record_sale(
            "Crossbody cash",
            [(products["BAG-002"], Decimal("1"))],
            cash,
            days_ago=16,
        )
        record_sale(
            "Oud preset 30ml",
            [(products["OUD-BULK"], Decimal("30"))],
            card,
            days_ago=18,
        )
        record_sale(
            "Lotion pair",
            [(products["SKIN-001"], Decimal("2"))],
            cash,
            days_ago=20,
        )

        if amina and amina.outstanding_balance > 0 and not CustomerPayment.objects.filter(note="Demo payment").exists():
            partial = min(Decimal("20.00"), amina.outstanding_balance)
            record_customer_payment(
                customer=amina,
                amount=partial,
                method=cash,
                user=cashier,
                note="Demo payment",
            )

        categories = {category.name: category for category in ExpenseCategory.objects.all()}
        demo_expenses = [
            (1, "Rent", Decimal("450.00"), "Monthly shop rent", cash),
            (2, "Utilities", Decimal("85.40"), "Electricity and water", cash),
            (3, "Salaries", Decimal("900.00"), "Staff salaries", cash),
            (5, "Transport", Decimal("35.00"), "Delivery runs", cash),
            (7, "Marketing", Decimal("120.00"), "Instagram promotion", card),
            (9, "Shop supplies", Decimal("64.25"), "Bags, tissue and ribbon", cash),
        ]
        for days_ago, category, amount, description, method in demo_expenses:
            reference = f"DEMO-EXP-{days_ago}"
            if Expense.objects.filter(reference=reference).exists():
                continue
            Expense.objects.create(
                category=categories.get(category),
                date=today - timedelta(days=days_ago),
                amount=amount,
                payment_method=method,
                method_name=method.name if method else "",
                description=description,
                reference=reference,
                user=owner,
            )

        if not StockAdjustment.objects.filter(note="Demo stock count").exists():
            adjust_stock(
                product=products["MUSK-BULK"],
                delta=Decimal("-5"),
                reason="damage",
                user=owner,
                note="Demo stock count",
            )
            adjust_stock(
                product=products["ACC-001"],
                delta=Decimal("2"),
                reason="stock_take",
                user=owner,
                note="Demo stock count",
            )

        if not CashReconciliation.objects.exists():
            opening = Decimal("100.00")
            expected = expected_cash(today, opening)
            CashReconciliation.objects.create(
                date=today,
                opening_float=opening,
                counted_cash=expected - Decimal("10.00"),
                expected_cash=expected,
                difference=Decimal("-10.00"),
                notes="Demo reconciliation with a small shortage",
                user=owner,
            )

        self.stdout.write(
            f"  Transactions: {Sale.objects.count()} sales, "
            f"{Expense.objects.count()} expenses, {PackRun.objects.count()} packing runs"
        )
