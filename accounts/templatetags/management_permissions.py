from django import template

from accounts.models import Role
from stores.decorators import user_has_store_permission

register = template.Library()

MANAGEMENT_MODULES = {
    "admin_accounts": {
        "title": "Admin Accounts",
        "description": "Manage administrator accounts, access, and status.",
        "permission": None,
        "super_admin_only": True,
        "url_name": "accounts:admin_list",
    },
    "stores": {
        "title": "Stores",
        "description": "Manage stores, store users, and store status.",
        "permission": "stores.view_store",
        "super_admin_only": False,
        "url_name": "stores:store_list",
    },
    "products": {
        "title": "Products",
        "description": "Manage product catalogue, pricing, and approvals.",
        "permission": "catalog.view_product",
        "super_admin_only": False,
        "url_name": "catalog:product_list",
    },
    "inventory": {
        "title": "Inventory",
        "description": "Inventory management tools are coming soon.",
        "permission": "accounts.access_inventory_module",
        "super_admin_only": False,
        "url_name": None,
    },
    "customers": {
        "title": "Customers",
        "description": "Customer management tools are coming soon.",
        "permission": "accounts.access_customers_module",
        "super_admin_only": False,
        "url_name": None,
    },
    "orders": {
        "title": "Orders",
        "description": "Order management tools are coming soon.",
        "permission": "accounts.access_orders_module",
        "super_admin_only": False,
        "url_name": None,
    },
    "delivery": {
        "title": "Delivery",
        "description": "Delivery management tools are coming soon.",
        "permission": "accounts.access_delivery_module",
        "super_admin_only": False,
        "url_name": None,
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


@register.filter
def has_store_perm(user, permission):
    """Template helper: Super Admin bypasses; Admin needs the Django permission."""
    return user_has_store_permission(user, permission)
