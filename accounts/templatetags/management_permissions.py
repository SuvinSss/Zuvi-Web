from django import template

from accounts.models import Role

register = template.Library()

MANAGEMENT_MODULES = {
    "admin_accounts": {
        "title": "Admin Accounts",
        "description": "Manage administrator accounts, access, and status.",
        "permission": None,
        "super_admin_only": True,
    },
    "stores": {
        "title": "Stores",
        "description": "Store management tools are coming soon.",
        "permission": "accounts.access_stores_module",
        "super_admin_only": False,
    },
    "products": {
        "title": "Products",
        "description": "Product management tools are coming soon.",
        "permission": "accounts.access_products_module",
        "super_admin_only": False,
    },
    "inventory": {
        "title": "Inventory",
        "description": "Inventory management tools are coming soon.",
        "permission": "accounts.access_inventory_module",
        "super_admin_only": False,
    },
    "customers": {
        "title": "Customers",
        "description": "Customer management tools are coming soon.",
        "permission": "accounts.access_customers_module",
        "super_admin_only": False,
    },
    "orders": {
        "title": "Orders",
        "description": "Order management tools are coming soon.",
        "permission": "accounts.access_orders_module",
        "super_admin_only": False,
    },
    "delivery": {
        "title": "Delivery",
        "description": "Delivery management tools are coming soon.",
        "permission": "accounts.access_delivery_module",
        "super_admin_only": False,
    },
}


@register.simple_tag
def module_definitions():
    return MANAGEMENT_MODULES


@register.filter
def can_access_module(user, module_key):
    module = MANAGEMENT_MODULES.get(module_key)
    if not user.is_authenticated or not module:
        return False
    if user.role == Role.SUPER_ADMIN:
        return True
    if module["super_admin_only"]:
        return False
    permission = module.get("permission")
    return bool(permission and user.has_perm(permission))
