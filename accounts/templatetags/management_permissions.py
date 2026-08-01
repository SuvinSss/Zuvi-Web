from django import template

from accounts.models import Role
from inventory.decorators import user_can_view_management_inventory
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
        "description": "Stock balances, purchases, adjustments, and history.",
        "permission": "inventory.view_inventorytransaction",
        "permissions_any": (
            "inventory.view_inventorytransaction",
            "inventory.view_all_inventory",
        ),
        "super_admin_only": False,
        "url_name": "inventory:management_inventory_list",
    },
    "customers": {
        "title": "Customers",
        "description": "Manage customer accounts, verification, and status.",
        "permission": "customers.view_customer",
        "super_admin_only": False,
        "url_name": "customers:customer_list",
    },
    "orders": {
        "title": "Orders",
        "description": "View and manage customer orders across stores.",
        "permission": "orders.view_order",
        "super_admin_only": False,
        "url_name": "orders:management_order_list",
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
    if module_key == "inventory":
        return user_can_view_management_inventory(user)
    permissions_any = module.get("permissions_any")
    if permissions_any:
        return any(user.has_perm(permission) for permission in permissions_any)
    permission = module.get("permission")
    return bool(permission and user.has_perm(permission))


@register.filter
def has_store_perm(user, permission):
    """Template helper: Super Admin bypasses; Admin needs the Django permission."""
    return user_has_store_permission(user, permission)


@register.filter
def has_customer_perm(user, permission):
    from customers.decorators import user_has_customer_permission

    return user_has_customer_permission(user, permission)


@register.filter
def has_order_perm(user, permission):
    from orders.decorators import user_has_order_permission

    return user_has_order_permission(user, permission)


@register.filter
def has_inventory_perm(user, permission):
    from inventory.decorators import user_has_inventory_permission

    return user_has_inventory_permission(user, permission)
