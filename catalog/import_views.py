from pathlib import Path
from django.utils import timezone
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from .import_contract import HEADERS, PRICING_FIELDS, ImportProblem, csv_text
from .import_files import read_bundle_image, staging_available
from .import_forms import ImportApprovalForm, ImportUploadForm
from .import_permissions import is_management, require_action, visible_jobs
from .import_services import approve_job, counts, create_job


def context(request, portal):
    user = require_action(request.user, 'template')
    if is_management(user) != (portal == 'management'):
        raise PermissionDenied
    prefix = 'catalog:import_' if portal == 'management' else 'catalog:store_import_'
    return dict(base_template='management/base.html' if portal == 'management' else 'store_portal/base.html',
                portal=portal, prefix=prefix, list_url=reverse(prefix + 'list'), create_url=reverse(prefix + 'create'),
                template_url=reverse(prefix + 'download', args=['template']), sample_url=reverse(prefix + 'download', args=['sample']),
                instructions_url=reverse(prefix + 'download', args=['instructions']), staging_available=staging_available(),
                can_price=is_management(user) and user.has_perm('catalog.manage_product_pricing'),
                can_create=user.has_perm('catalog.add_importjob') and (not is_management(user) or user.has_perm('catalog.add_product')))


def job_for(request, pk):
    job = get_object_or_404(visible_jobs(request.user), pk=pk)
    require_action(request.user, 'view', store=job.store, job=job)
    return job


def private(response):
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@require_GET
def import_list(request, portal):
    ctx = context(request, portal)
    page = Paginator(visible_jobs(request.user).defer('csv_bytes', 'image_manifest', 'approved_snapshot'), 25).get_page(request.GET.get('page'))
    ctx['page'] = page
    for job in page:
        job.detail_url = reverse(ctx['prefix'] + 'detail', args=[job.pk])
    return private(render(request, 'catalog/imports/list.html', ctx))


@login_required
@require_http_methods(['GET', 'POST'])
def import_create(request, portal):
    ctx = context(request, portal)
    require_action(request.user, 'create')
    form = ImportUploadForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        upload = form.cleaned_data['csv_file']
        try:
            job = create_job(actor=request.user, store=form.cleaned_data['store'], content=upload.read(5 * 1024 * 1024 + 1), filename=upload.name, job_id=form.cleaned_data['nonce'])
        except ImportProblem as exc:
            form.add_error(None, exc.message)
        else:
            return redirect(ctx['prefix'] + 'detail', pk=job.pk)
    ctx.update(form=form, headers=HEADERS)
    return private(render(request, 'catalog/imports/create.html', ctx))


@login_required
@require_GET
def import_detail(request, portal, pk):
    ctx = context(request, portal)
    job = job_for(request, pk)
    page = Paginator(job.rows.select_related('product'), 50).get_page(request.GET.get('page'))
    for row in page:
        row.expired = bool(row.payload.get('data', {}).get('expiry_date') and row.payload['data']['expiry_date'] < timezone.localdate().isoformat())
        row.display = dict(row.payload.get('data') or row.payload.get('raw', {}))
        if not ctx['can_price']:
            for key in (*PRICING_FIELDS, 'price_preview'):
                row.display.pop(key, None)
        row.preview_images = [dict(filename=image['filename'], url=reverse(ctx['prefix'] + 'image', args=[job.pk, row.row_number, pos])) for pos, image in enumerate(row.payload.get('data', {}).get('images', []), 1)] if job.image_bundle_key and job.image_manifest else []
    canonical_url = None
    if job.duplicate_of_id and visible_jobs(request.user).filter(pk=job.duplicate_of_id).exists():
        canonical_url = reverse(ctx['prefix'] + 'detail', args=[job.duplicate_of_id])
    ctx.update(job=job, page=page, counts=counts(job), canonical_url=canonical_url,
               can_approve=portal == 'management' and request.user.has_perm('catalog.approve_importjob') and request.user.has_perm('catalog.add_product'),
               approval_form=ImportApprovalForm(initial={'expected_hash': job.fingerprint}),
               approve_url=reverse('catalog:import_approve', args=[job.pk]), report_url=reverse(ctx['prefix'] + 'report', args=[job.pk]))
    return private(render(request, 'catalog/imports/detail.html', ctx))


@login_required
@require_POST
def import_approve(request, pk):
    job = job_for(request, pk)
    require_action(request.user, 'approve', store=job.store, job=job)
    form = ImportApprovalForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Confirm that you reviewed the current preview before approving.')
    else:
        try:
            approve_job(job_id=pk, actor=request.user, expected_hash=form.cleaned_data['expected_hash'])
            messages.success(request, 'Import approved. Awaiting the supervised operator; no products have been published.')
        except ImportProblem as exc:
            messages.error(request, exc.message)
    return redirect('catalog:import_detail', pk=pk)


@login_required
@require_GET
def import_download(request, portal, kind):
    context(request, portal)
    names = {'template': 'catalog-import-template-v1.csv', 'sample': 'catalog-import-sample-v1.csv', 'instructions': 'catalog-import.md'}
    if kind not in names:
        raise Http404
    filename = names[kind]
    response = HttpResponse((Path(settings.BASE_DIR) / 'docs' / filename).read_bytes(), content_type='text/csv; charset=utf-8' if kind != 'instructions' else 'text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return private(response)


@login_required
@require_GET
def import_report(request, portal, pk):
    ctx = context(request, portal)
    job = job_for(request, pk)
    headers = ['row_number', 'external_sku', 'name', 'status', 'attempts', 'product_code', 'error_codes', 'errors', 'orphan_objects_possible']
    values = [headers]
    for row in job.rows.select_related('product').iterator(chunk_size=50):
        raw = row.payload.get('raw', {})
        values.append([row.row_number, raw.get('external_sku'), raw.get('name'), row.status, row.attempts,
                       row.product.product_code if row.product else '', '|'.join(e['code'] for e in row.errors),
                       ' | '.join(e['message'] for e in row.errors), row.result.get('orphan_objects_possible', False)])
    response = HttpResponse(csv_text(values), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="catalog-import-{job.pk}-results.csv"'
    return private(response)


@login_required
@require_GET
def import_image(request, portal, pk, row_number, position):
    context(request, portal)
    job = job_for(request, pk)
    row = get_object_or_404(job.rows, row_number=row_number)
    images = row.payload.get('data', {}).get('images', [])
    if not 1 <= position <= len(images):
        raise Http404
    try:
        content = read_bundle_image(job, images[position - 1]['filename'])
    except ImportProblem:
        return private(HttpResponse('Prepared image unavailable. Ask the operator to check the approved bundle.', status=409, content_type='text/plain'))
    response = HttpResponse(content, content_type={'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}[images[position - 1]['format']])
    response['Content-Disposition'] = 'inline'
    return private(response)
