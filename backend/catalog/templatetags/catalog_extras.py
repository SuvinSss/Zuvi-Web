from django import template

register = template.Library()

# Checked in order — first keyword found in the (lowercased) category name wins.
_CATEGORY_ICONS = (
    ("fruit", "\U0001F966"),
    ("veg", "\U0001F966"),
    ("atta", "\U0001F33E"),
    ("rice", "\U0001F33E"),
    ("grain", "\U0001F33E"),
    ("dairy", "\U0001F95B"),
    ("bakery", "\U0001F35E"),
    ("bread", "\U0001F35E"),
    ("beverage", "\U0001F964"),
    ("drink", "\U0001F964"),
    ("snack", "\U0001F37F"),
    ("spice", "\U0001F336"),
    ("masala", "\U0001F336"),
    ("care", "\U0001F9F4"),
    ("household", "\U0001F9F9"),
    ("clean", "\U0001F9F9"),
    ("kitchen", "\U0001F373"),
    ("home", "\U0001F3E0"),
    ("grocery", "\U0001F6D2"),
    ("meat", "\U0001F357"),
    ("fish", "\U0001F41F"),
    ("baby", "\U0001F37C"),
    ("pet", "\U0001F43E"),
    ("stationery", "\U0000270F"),
    ("electronic", "\U0001F50C"),
    ("fancy", "\U00002728"),
)
_DEFAULT_ICON = "\U0001F6CD"


@register.filter
def category_icon(name):
    """Best-effort emoji for a category name, based on keyword matching."""
    lowered = (name or "").lower()
    for keyword, icon in _CATEGORY_ICONS:
        if keyword in lowered:
            return icon
    return _DEFAULT_ICON
