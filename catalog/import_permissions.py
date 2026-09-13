"""Existing role/store policies plus Django's import action permissions."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from accounts.decorators import can_access_management_portal
from accounts.models import Role
from stores.decorators import resolve_store_portal_membership
from stores.models import Store
from stores.status import store_allows_portal_access

from .import_contract import PRICING_FIELDS
from .models import ImportJob


def fresh_user(user):
    if user is None or not getattr(user, 'pk', None):
        raise PermissionDenied('An active authorized import user is required.')
    try:
        return get_user_model().objects.get(pk=user.pk, is_active=True)
    except get_user_model().DoesNotExist:
        raise PermissionDenied('Import permission is no longer available.')


def is_management(user):
    return can_access_management_portal(user)


def membership_for(user):
    member, denial = resolve_store_portal_membership(user)
    if member is None:
        raise PermissionDenied('An active assigned store is required.')
    return member


def require_action(user, action, *, store=None, job=None):
    user = fresh_user(user)
    management = is_management(user)
    if not management and user.role != Role.STORE_USER:
        raise PermissionDenied('This role cannot access catalogue imports.')
    member = None if management else membership_for(user)
    if store is not None:
        store = Store.objects.get(pk=store.pk)
        if not store.is_active or not store_allows_portal_access(store) or (member and member.store_id != store.pk):
            raise PermissionDenied('This store is unavailable for this import user.')
    if job and member and (job.created_by_id != user.pk or job.store_id != member.store_id):
        raise PermissionDenied('Import job is not accessible.')
    grants = {'view': ('view_importjob',), 'create': ('add_importjob', 'view_importjob'), 'approve': ('approve_importjob', 'view_importjob'), 'execute': ('execute_importjob', 'view_importjob')}
    if action == 'template':
        permitted = user.has_perm('catalog.add_importjob') or user.has_perm('catalog.view_importjob')
    else:
        permitted = all(user.has_perm('catalog.' + grant) for grant in grants[action])
    if not permitted or (action in ('approve', 'execute') and not management):
        raise PermissionDenied('You do not have permission for this import action.')
    if management and action != 'template':
        product_perm = 'view_product' if action == 'view' else 'add_product'
        if not user.has_perm('catalog.' + product_perm):
            raise PermissionDenied('The corresponding product permission is required.')
    return user


def visible_jobs(user):
    user = require_action(user, 'view')
    jobs = ImportJob.objects.select_related('store', 'created_by', 'approved_by', 'operator')
    if is_management(user):
        return jobs
    member = membership_for(user)
    return jobs.filter(created_by=user, store_id=member.store_id)


def available_stores(user):
    user = require_action(user, 'create')
    if is_management(user):
        return Store.objects.filter(is_active=True, status='ACTIVE')
    return Store.objects.filter(pk=membership_for(user).store_id)


def require_capabilities(user, store, raw):
    user = fresh_user(user)
    if is_management(user):
        if not user.has_perm('catalog.add_product'):
            raise PermissionDenied('Product creation permission is required.')
        pricing = user.has_perm('catalog.manage_product_pricing')
        inventory = user.has_perm('inventory.adjust_inventory')
    else:
        require_action(user, 'create', store=store)
        member = membership_for(user)
        pricing, inventory = False, member.can_manage_inventory
    if any(str(raw.get(k) or '').strip() for k in PRICING_FIELDS) and not pricing:
        raise PermissionDenied('Management pricing is not allowed for this requester, approver or operator.')
    if any(str(raw.get(k) or '').strip() for k in ('opening_stock', 'opening_stock_reason')) and not inventory:
        raise PermissionDenied('Opening stock is not allowed for this requester, approver or operator.')


def require_participants(job, operator, *, approver=None, raw=None):
    creator = require_action(job.created_by, 'create', store=job.store)
    operator = require_action(operator, 'execute', store=job.store, job=job)
    approving = approver or job.approved_by
    if approving is not None:
        approving = require_action(approving, 'approve', store=job.store, job=job)
    if raw is not None:
        for principal in (creator, operator, approving):
            if principal is not None:
                require_capabilities(principal, job.store, raw)
    return operator
