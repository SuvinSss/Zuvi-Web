"""Single definition of the bulk-import columns (template, parser and docs)."""
from collections import namedtuple

Column = namedtuple("Column", "key required description example")

COLUMNS = (
    Column("store_code", True, "Code of the store that owns the product (see the Reference sheet).", "ST123ABC"),
    Column("sku", True, "Unique per store, up to 64 characters. Used to detect duplicates and to match updates.", "RICE-5KG"),
    Column("name", True, "Product name, up to 200 characters.", "Matta Rice 5 kg"),
    Column("category", True, "Existing category name, or 'Parent / Child' when the name is not unique.", "Groceries / Rice"),
    Column("store_price", True, "Store price as a number, 0 or more, at most 2 decimals. Selling price is set by management.", "245.00"),
    Column("brand", False, "Existing brand name.", "Zuvi Farms"),
    Column("description", False, "Free text.", "Unpolished red matta rice."),
    Column("unit", False, "PIECE, PACK, BOX, DOZEN, KG, GRAM, LITER, ML or METER (default PIECE).", "KG"),
    Column("unit_value", False, "Amount per unit, e.g. 5 for 5 KG (default 1).", "5"),
    Column("low_stock_threshold", False, "Low-stock alert level, 0 or more (default 0).", "10"),
    Column("manufacturing_date", False, "YYYY-MM-DD, not in the future.", "2026-09-01"),
    Column("expiry_date", False, "YYYY-MM-DD, on or after the manufacturing date.", "2027-09-01"),
    Column("tags", False, "Comma-separated existing tag names.", "organic, staple"),
    Column("image_file", False, "File name of an image inside the optional images ZIP.", "rice-5kg.jpg"),
    Column("image_url", False, "https image URL. Only used when 'Allow image URLs' is ticked for the import.", ""),
    Column("image_alt_text", False, "Alternative text for the image (up to 200 characters).", "Bag of matta rice"),
)
KEYS = tuple(column.key for column in COLUMNS)
REQUIRED = tuple(column.key for column in COLUMNS if column.required)
TEXT_KEYS = frozenset(
    {"store_code", "sku", "name", "category", "brand", "description", "tags",
     "image_file", "image_url", "image_alt_text"}
)
