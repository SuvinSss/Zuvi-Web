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

# Header names people commonly use. Matching is exact after normalisation (lower case, symbols to "_"),
# never fuzzy: an unrecognised header is shown to the user for manual mapping instead of being guessed.
ALIASES = {
    "store_code": ("store", "store_id", "shop", "shop_code", "store_name_code", "outlet", "outlet_code"),
    "sku": ("item_code", "product_code", "code", "sku_code", "item_sku", "article_no", "barcode_sku"),
    "name": ("product_name", "item_name", "title", "product", "product_title", "item", "name_of_product"),
    "category": ("product_category", "category_name", "cat", "department"),
    "store_price": ("price", "selling_price", "sale_price", "rate", "unit_price", "store_rate"),
    "brand": ("brand_name", "manufacturer", "make", "company"),
    "description": ("details", "product_description", "desc", "about", "notes"),
    "unit": ("uom", "unit_of_measure", "measure", "units"),
    "unit_value": ("pack_size", "size", "quantity_per_unit", "net_quantity", "weight", "volume"),
    "low_stock_threshold": ("reorder_level", "min_stock", "low_stock", "reorder_point", "minimum_stock"),
    "manufacturing_date": ("mfg_date", "manufactured_on", "mfg", "date_of_manufacture", "production_date"),
    "expiry_date": ("exp_date", "expiry", "expires_on", "best_before", "use_by", "expiration_date"),
    "tags": ("labels", "keywords", "tag"),
    "image_file": ("image", "image_name", "photo", "photo_file", "picture", "image_filename"),
    "image_url": ("image_link", "photo_url", "picture_url", "img_url"),
    "image_alt_text": ("alt_text", "image_alt", "alt"),
}
# "stock" / "quantity" columns are deliberately NOT aliased: stock is changed only through inventory
# movements, so those columns are reported as ignored instead of silently writing a quantity.


def normalise_header(value) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower().replace("*", "")).strip("_")


_LOOKUP = {}
for _key in KEYS:
    _LOOKUP[_key] = (_key, "exact")
for _key, _names in ALIASES.items():
    for _name in _names:
        _LOOKUP.setdefault(_name, (_key, "alias"))


def resolve_headers(raw_headers, mapping=None):
    """Map source headers to canonical keys.

    Returns ``(index_to_key, proposal)``. ``mapping`` ({source header: key or ""}) comes from the user and
    wins over automatic matching. A canonical key is used by at most one column (the first wins).
    """
    mapping = {normalise_header(k): v for k, v in (mapping or {}).items()}
    taken, resolved, proposal = {}, {}, []
    exact = {normalise_header(h) for h in raw_headers if normalise_header(h) in KEYS}
    for index, raw in enumerate(raw_headers):
        norm = normalise_header(raw)
        if not norm:
            continue
        key, how = None, None
        if norm in mapping:
            chosen = mapping[norm]
            if chosen in KEYS:
                key, how = chosen, "manual"
            else:
                how = "ignored"
        elif norm in _LOOKUP:
            key, how = _LOOKUP[norm]
            if how == "alias" and key in exact:
                key = None  # a real column with the canonical name exists; do not double-map
        if key and key in taken:
            key, how = None, "duplicate"
        if key:
            taken[key] = index
            resolved[index] = key
        proposal.append({"source": str(raw), "key": key, "how": how})
    return resolved, proposal
