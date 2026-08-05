import io
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from catalog.models import Brand, Product, ProductCategory, ProductStatus, Tag
from catalog.pricing import DiscountType, MarginType
from catalog.services import (
    add_product_image,
    apply_admin_pricing,
    create_product,
    record_product_status_change,
)
from inventory.services import record_opening_stock
from stores.models import Store, StoreStatus

PIECE, PACK, BOX, DOZEN, KG, GRAM, LITER, ML, METER = (
    "PIECE",
    "PACK",
    "BOX",
    "DOZEN",
    "KG",
    "GRAM",
    "LITER",
    "ML",
    "METER",
)

# name -> parent name (None for top-level)
CATEGORY_SPECS = [
    ("Fruits & Vegetables", None),
    ("Dairy & Bakery", None),
    ("Beverages", None),
    ("Snacks & Branded Foods", None),
    ("Personal Care", None),
    ("Home & Kitchen", None),
    ("Grocery", None),
    ("Atta & Rice", "Grocery"),
    ("Spices & Masala", "Grocery"),
]

BRAND_NAMES = [
    "Amul",
    "Tata",
    "Nestle",
    "Britannia",
    "Parle",
    "Dabur",
    "Colgate",
    "Patanjali",
    "Fortune",
    "Haldiram's",
    "Coca-Cola",
    "Real",
    "Lay's",
    "MDH",
    "Everest",
    "Harpic",
    "Vim",
    "Lifebuoy",
]

TAG_NAMES = [
    "Organic",
    "Best Seller",
    "New Arrival",
    "Combo Offer",
    "Eco Friendly",
    "On Sale",
    "Trending",
    "Premium",
    "Family Pack",
]

CATEGORY_COLORS = {
    "Fruits & Vegetables": (76, 175, 80),
    "Dairy & Bakery": (255, 193, 7),
    "Beverages": (33, 150, 243),
    "Snacks & Branded Foods": (255, 87, 34),
    "Personal Care": (156, 39, 176),
    "Home & Kitchen": (0, 150, 136),
    "Grocery": (121, 85, 72),
    "Atta & Rice": (121, 85, 72),
    "Spices & Masala": (233, 30, 99),
}

# Each entry: name, sku, category, brand, unit, unit_value, store_price,
# margin_type, margin, discount_type, discount_value, stock, tags, featured, perishable
PRODUCTS = [
    ("Fresh Tomatoes", "VEG-TOM-01", "Fruits & Vegetables", None, KG, "1.000", "18.00", MarginType.PERCENTAGE, "15.00", "", None, "150.000", ["Organic"], False, True),
    ("Red Onions", "VEG-ONI-01", "Fruits & Vegetables", None, KG, "1.000", "22.00", MarginType.PERCENTAGE, "15.00", "", None, "200.000", [], False, True),
    ("Robusta Bananas", "VEG-BAN-01", "Fruits & Vegetables", None, KG, "1.000", "25.00", MarginType.PERCENTAGE, "12.00", "", None, "120.000", ["Organic"], False, True),
    ("Potatoes", "VEG-POT-01", "Fruits & Vegetables", None, KG, "1.000", "20.00", MarginType.PERCENTAGE, "12.00", "", None, "180.000", [], False, True),
    ("Amul Butter", "DAI-BUT-01", "Dairy & Bakery", "Amul", GRAM, "500.000", "210.00", MarginType.PERCENTAGE, "10.00", "", None, "60.000", ["Best Seller"], True, True),
    ("Amul Milk", "DAI-MLK-01", "Dairy & Bakery", "Amul", LITER, "1.000", "58.00", MarginType.PERCENTAGE, "8.00", "", None, "100.000", [], False, True),
    ("Britannia Bread", "DAI-BRD-01", "Dairy & Bakery", "Britannia", PACK, "1.000", "42.00", MarginType.PERCENTAGE, "15.00", "", None, "80.000", ["New Arrival"], False, True),
    ("Nestle Curd Cup", "DAI-CRD-01", "Dairy & Bakery", "Nestle", GRAM, "400.000", "45.00", MarginType.PERCENTAGE, "10.00", "", None, "70.000", [], False, True),
    ("Coca-Cola Soft Drink", "BEV-COK-01", "Beverages", "Coca-Cola", ML, "750.000", "40.00", MarginType.PERCENTAGE, "18.00", DiscountType.FIXED, "5.00", "150.000", ["On Sale"], False, False),
    ("Real Mixed Fruit Juice", "BEV-JUI-01", "Beverages", "Real", LITER, "1.000", "110.00", MarginType.PERCENTAGE, "20.00", "", None, "90.000", ["Family Pack"], False, False),
    ("Tata Tea Gold", "BEV-TEA-01", "Beverages", "Tata", GRAM, "500.000", "240.00", MarginType.PERCENTAGE, "15.00", "", None, "60.000", ["Best Seller"], False, False),
    ("Nescafe Classic Coffee", "BEV-CFE-01", "Beverages", "Nestle", GRAM, "100.000", "260.00", MarginType.PERCENTAGE, "12.00", "", None, "50.000", ["Premium"], True, False),
    ("Parle-G Biscuits", "SNK-BIS-01", "Snacks & Branded Foods", "Parle", GRAM, "800.000", "90.00", MarginType.PERCENTAGE, "20.00", "", None, "200.000", ["Best Seller"], True, False),
    ("Haldiram's Bhujia", "SNK-BHJ-01", "Snacks & Branded Foods", "Haldiram's", GRAM, "400.000", "95.00", MarginType.PERCENTAGE, "22.00", DiscountType.PERCENTAGE, "10.00", "120.000", ["On Sale", "Trending"], False, False),
    ("Britannia Good Day Cookies", "SNK-COO-01", "Snacks & Branded Foods", "Britannia", GRAM, "600.000", "85.00", MarginType.PERCENTAGE, "18.00", "", None, "100.000", ["New Arrival"], False, False),
    ("Lay's Classic Salted Chips", "SNK-CHP-01", "Snacks & Branded Foods", "Lay's", GRAM, "90.000", "20.00", MarginType.PERCENTAGE, "25.00", "", None, "300.000", ["Trending"], False, False),
    ("Dabur Chyawanprash", "PC-CHY-01", "Personal Care", "Dabur", GRAM, "500.000", "220.00", MarginType.PERCENTAGE, "15.00", "", None, "40.000", ["Premium", "Organic"], False, False),
    ("Colgate Strong Teeth Toothpaste", "PC-TPS-01", "Personal Care", "Colgate", GRAM, "200.000", "95.00", MarginType.PERCENTAGE, "20.00", "", None, "150.000", ["Best Seller"], False, False),
    ("Patanjali Aloe Vera Gel", "PC-ALO-01", "Personal Care", "Patanjali", ML, "150.000", "90.00", MarginType.PERCENTAGE, "18.00", "", None, "80.000", ["Organic", "Eco Friendly"], False, False),
    ("Lifebuoy Soap Pack of 4", "PC-SOP-01", "Personal Care", "Lifebuoy", PACK, "4.000", "120.00", MarginType.PERCENTAGE, "15.00", DiscountType.FIXED, "10.00", "100.000", ["Family Pack", "On Sale"], False, False),
    ("Fortune Sunflower Oil", "GRO-OIL-01", "Grocery", "Fortune", LITER, "1.000", "145.00", MarginType.PERCENTAGE, "10.00", "", None, "90.000", ["Best Seller"], False, False),
    ("Fortune Basmati Rice", "ATR-RIC-01", "Atta & Rice", "Fortune", KG, "5.000", "480.00", MarginType.PERCENTAGE, "12.00", "", None, "50.000", ["Premium"], False, False),
    ("Aashirvad Atta", "ATR-ATT-01", "Atta & Rice", "Aashirvad", KG, "5.000", "260.00", MarginType.PERCENTAGE, "10.00", "", None, "70.000", ["Best Seller", "Family Pack"], True, False),
    ("MDH Garam Masala", "SPM-GAR-01", "Spices & Masala", "MDH", GRAM, "100.000", "65.00", MarginType.PERCENTAGE, "20.00", "", None, "60.000", ["Organic"], False, False),
    ("Everest Sabzi Masala", "SPM-SAB-01", "Spices & Masala", "Everest", GRAM, "100.000", "55.00", MarginType.PERCENTAGE, "20.00", "", None, "60.000", ["New Arrival"], False, False),
    ("Harpic Toilet Cleaner", "HK-CLN-01", "Home & Kitchen", "Harpic", LITER, "1.000", "95.00", MarginType.PERCENTAGE, "15.00", "", None, "70.000", ["Eco Friendly"], False, False),
    ("Vim Dishwash Gel", "HK-DSH-01", "Home & Kitchen", "Vim", ML, "500.000", "75.00", MarginType.PERCENTAGE, "15.00", DiscountType.PERCENTAGE, "5.00", "90.000", ["On Sale"], False, False),
]


def _decimal(value):
    return None if value is None else Decimal(value)


def _make_placeholder_image(text, color):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (600, 600), color)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()

    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] > 520 and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)

    line_height = 44
    total_height = line_height * len(lines)
    y = (600 - total_height) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        width = bbox[2] - bbox[0]
        x = (600 - width) // 2
        draw.text((x, y), line, fill="white", font=font)
        y += line_height

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    buffer.seek(0)
    return ContentFile(buffer.read(), name="seed-product.jpg")


class Command(BaseCommand):
    help = (
        "Seed sample ProductCategory, Brand, Tag and Product rows (with images, "
        "pricing, stock and approval) so the storefront has visible catalogue "
        "data. Safe to re-run: existing categories/brands/tags/SKUs are skipped."
    )

    def handle(self, *args, **options):
        actor = User.objects.filter(is_superuser=True).order_by("pk").first()
        if actor is None:
            raise CommandError(
                "No superuser found. Create one with 'manage.py createsuperuser' "
                "first, since seeded products need an approving admin."
            )

        stores = list(
            Store.objects.filter(
                status=StoreStatus.ACTIVE, is_active=True
            ).order_by("pk")
        )
        if not stores:
            raise CommandError(
                "No active Store found. Create and activate at least one Store "
                "before seeding sample products."
            )

        categories = self._seed_categories()
        brands = self._seed_brands()
        tags = self._seed_tags()

        created_count = 0
        skipped_count = 0

        for index, spec in enumerate(PRODUCTS):
            (
                name,
                sku,
                category_name,
                brand_name,
                unit,
                unit_value,
                store_price,
                margin_type,
                margin,
                discount_type,
                discount_value,
                stock,
                tag_names,
                featured,
                perishable,
            ) = spec

            store = stores[index % len(stores)]

            if Product.objects.filter(store=store, sku=sku).exists():
                skipped_count += 1
                continue

            try:
                self._create_one_product(
                    actor=actor,
                    store=store,
                    name=name,
                    sku=sku,
                    category=categories[category_name],
                    brand=brands.get(brand_name),
                    unit=unit,
                    unit_value=_decimal(unit_value),
                    store_price=_decimal(store_price),
                    margin_type=margin_type,
                    margin=_decimal(margin),
                    discount_type=discount_type,
                    discount_value=_decimal(discount_value),
                    stock=_decimal(stock),
                    tag_ids=[tags[t].pk for t in tag_names],
                    featured=featured,
                    perishable=perishable,
                )
                created_count += 1
            except Exception as exc:  # noqa: BLE001 - report and continue seeding
                self.stdout.write(
                    self.style.WARNING(f"Skipped '{name}' for {store.name}: {exc}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created_count} product(s); skipped {skipped_count} "
                "already-existing SKU(s)."
            )
        )

    def _seed_categories(self):
        by_name = {}
        for name, parent_name in CATEGORY_SPECS:
            if parent_name is not None:
                continue
            category, _ = ProductCategory.objects.get_or_create(
                name=name, defaults={"description": f"{name} products."}
            )
            by_name[name] = category

        for name, parent_name in CATEGORY_SPECS:
            if parent_name is None:
                continue
            category, _ = ProductCategory.objects.get_or_create(
                name=name,
                defaults={
                    "description": f"{name} products.",
                    "parent": by_name[parent_name],
                },
            )
            by_name[name] = category

        return by_name

    def _seed_brands(self):
        by_name = {}
        for name in BRAND_NAMES:
            brand, _ = Brand.objects.get_or_create(name=name)
            by_name[name] = brand
        return by_name

    def _seed_tags(self):
        by_name = {}
        for name in TAG_NAMES:
            tag, _ = Tag.objects.get_or_create(name=name)
            by_name[name] = tag
        return by_name

    @transaction.atomic
    def _create_one_product(
        self,
        *,
        actor,
        store,
        name,
        sku,
        category,
        brand,
        unit,
        unit_value,
        store_price,
        margin_type,
        margin,
        discount_type,
        discount_value,
        stock,
        tag_ids,
        featured,
        perishable,
    ):
        today = timezone.localdate()
        product_data = {
            "name": name,
            "sku": sku,
            "category": category,
            "brand": brand,
            "unit": unit,
            "unit_value": unit_value,
            "store_price": store_price,
            "low_stock_threshold": Decimal("10.000"),
            "description": f"{name} available from {store.name}.",
            "is_featured": featured,
        }
        if perishable:
            product_data["manufacturing_date"] = today - timezone.timedelta(days=3)
            product_data["expiry_date"] = today + timezone.timedelta(days=21)

        product = create_product(
            store=store,
            product_data=product_data,
            created_by=actor,
            tag_ids=tag_ids,
            initial_status=ProductStatus.PENDING,
        )

        color = CATEGORY_COLORS.get(category.name, (96, 96, 96))
        image_file = _make_placeholder_image(name, color)
        add_product_image(
            product=product,
            image=image_file,
            alt_text=name,
            is_primary=True,
        )

        apply_admin_pricing(
            product=product,
            profit_margin_type=margin_type,
            profit_margin=margin,
            discount_type=discount_type or "",
            discount_value=discount_value,
            changed_by=actor,
            reason="Seed sample data",
        )

        record_opening_stock(
            product=product,
            store=store,
            quantity=stock,
            actor=actor,
            reason="Seed sample stock",
        )

        record_product_status_change(
            product=product,
            new_status=ProductStatus.APPROVED,
            changed_by=actor,
            reason="Seed sample data auto-approval",
        )
