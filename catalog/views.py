from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import F, Prefetch, Q
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from config.storage_errors import image_request_errors

from stores.decorators import store_portal_required
from stores.models import Store

from .decorators import catalog_permission_required, user_has_catalog_permission
from .forms import (
    BrandForm,
    ManagementProductCreateForm,
    ManagementProductForm,
    ProductCategoryForm,
    ProductImageForm,
    ProductPricingForm,
    ProductStatusChangeForm,
    StoreProductCreateForm,
    StoreProductForm,
    TagForm,
)
from .models import (
    Brand,
    Product,
    ProductCategory,
    ProductImage,
    ProductStatus,
    Tag,
)
from .services import (
    add_product_image,
    apply_admin_pricing,
    create_product,
    delete_product_image,
    get_portal_product_or_404,
    portal_products_queryset,
    record_product_status_change,
    set_primary_product_image,
    update_product,
)
from .status import allowed_next_statuses, permission_for_transition
from .validators import MAX_IMAGES_PER_PRODUCT


def _get_product_or_404(pk):
    try:
        return (
            Product.objects.select_related(
                "store",
                "category",
                "brand",
                "created_by",
                "updated_by",
            )
            .prefetch_related(
                "tags",
                Prefetch(
                    "images",
                    queryset=ProductImage.objects.order_by("sort_order", "pk"),
                ),
                "status_history__changed_by",
                "price_history__changed_by",
            )
            .get(pk=pk)
        )
    except Product.DoesNotExist as exc:
        raise Http404("Product not found.") from exc


def _management_available_transitions(user, product):
    next_statuses = allowed_next_statuses(product.status)
    available = []
    for status_value in next_statuses:
        required = permission_for_transition(product.status, status_value)
        if required and user_has_catalog_permission(user, required):
            available.append(status_value)
    return available


# ----- Management: products -----


@catalog_permission_required("catalog.view_product")
def product_list_view(request):
    primary_images = Prefetch(
        "images",
        queryset=ProductImage.objects.filter(is_primary=True),
        to_attr="primary_image_list",
    )
    queryset = (
        Product.objects.select_related("store", "category", "brand")
        .prefetch_related(primary_images)
        .order_by("-created_at")
    )
    search_query = request.GET.get("q", "").strip()
    store_filter = request.GET.get("store", "").strip()
    status_filter = request.GET.get("status", "").strip()
    category_filter = request.GET.get("category", "").strip()
    brand_filter = request.GET.get("brand", "").strip()
    stock_filter = request.GET.get("stock", "").strip()
    is_active_filter = request.GET.get("is_active", "").strip()

    if search_query:
        queryset = queryset.filter(
            Q(product_code__icontains=search_query)
            | Q(name__icontains=search_query)
            | Q(sku__icontains=search_query)
            | Q(store__name__icontains=search_query)
            | Q(store__store_code__icontains=search_query)
            | Q(brand__name__icontains=search_query)
        ).distinct()
    if store_filter:
        queryset = queryset.filter(store_id=store_filter)
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    if category_filter:
        queryset = queryset.filter(category_id=category_filter)
    if brand_filter:
        queryset = queryset.filter(brand_id=brand_filter)
    if stock_filter == "in_stock":
        queryset = queryset.filter(stock_quantity__gt=0)
    elif stock_filter == "out_of_stock":
        queryset = queryset.filter(stock_quantity__lte=0)
    if is_active_filter == "true":
        queryset = queryset.filter(is_active=True)
    elif is_active_filter == "false":
        queryset = queryset.filter(is_active=False)

    page_obj = Paginator(queryset, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "management/products/list.html",
        {
            "page_obj": page_obj,
            "search_query": search_query,
            "store_filter": store_filter,
            "status_filter": status_filter,
            "category_filter": category_filter,
            "brand_filter": brand_filter,
            "stock_filter": stock_filter,
            "is_active_filter": is_active_filter,
            "status_choices": ProductStatus.choices,
            "stores": Store.objects.order_by("name"),
            "categories": ProductCategory.objects.order_by("name"),
            "brands": Brand.objects.order_by("name"),
            "can_add_product": user_has_catalog_permission(
                request.user, "catalog.add_product"
            ),
            "can_view_categories": user_has_catalog_permission(
                request.user, "catalog.view_productcategory"
            ),
            "can_view_brands": user_has_catalog_permission(
                request.user, "catalog.view_brand"
            ),
            "can_view_tags": user_has_catalog_permission(
                request.user, "catalog.view_tag"
            ),
        },
    )


@catalog_permission_required("catalog.view_product")
def product_detail_view(request, pk):
    product = _get_product_or_404(pk)
    available_transitions = _management_available_transitions(request.user, product)
    return render(
        request,
        "management/products/detail.html",
        {
            "product": product,
            "status_form": ProductStatusChangeForm(
                current_status=product.status,
                allowed_statuses=available_transitions,
            ),
            "available_transitions": available_transitions,
            "can_change_product": user_has_catalog_permission(
                request.user, "catalog.change_product"
            ),
            "can_set_pricing": user_has_catalog_permission(
                request.user, "catalog.manage_product_pricing"
            ),
            "can_change_status": bool(available_transitions),
            "can_manage_images": user_has_catalog_permission(
                request.user, "catalog.change_product"
            ),
        },
    )


@catalog_permission_required("catalog.add_product")
def product_create_view(request):
    form = ManagementProductCreateForm(
        request.POST or None,
        request.FILES or None,
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        save_as_draft = data.pop("save_as_draft", False)
        store = data.pop("store")
        tags = data.pop("tags", [])
        data.pop("selling_price", None)
        data.pop("final_price", None)
        initial_status = (
            ProductStatus.DRAFT if save_as_draft else ProductStatus.PENDING
        )
        product = create_product(
            store=store,
            product_data=data,
            created_by=request.user,
            tag_ids=[t.pk for t in tags],
            initial_status=initial_status,
            request=request,
        )
        messages.success(
            request,
            f"Product {product.product_code} created successfully.",
        )
        return redirect("catalog:product_detail", pk=product.pk)

    return render(
        request,
        "management/products/create.html",
        {"form": form},
    )


@catalog_permission_required("catalog.change_product")
def product_edit_view(request, pk):
    product = _get_product_or_404(pk)
    form = ManagementProductForm(
        request.POST or None,
        request.FILES or None,
        instance=product,
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        data.pop("store", None)
        tags = data.pop("tags", [])
        data.pop("selling_price", None)
        data.pop("final_price", None)
        update_product(
            product=product,
            product_data=data,
            updated_by=request.user,
            tag_ids=[t.pk for t in tags],
            request=request,
            actor_is_store_user=False,
        )
        messages.success(request, "Product updated successfully.")
        return redirect("catalog:product_detail", pk=product.pk)

    return render(
        request,
        "management/products/edit.html",
        {"product": product, "form": form},
    )


@catalog_permission_required("catalog.manage_product_pricing")
def product_pricing_view(request, pk):
    product = _get_product_or_404(pk)
    form = ProductPricingForm(
        request.POST or None,
        product=product,
    )
    if request.method == "POST" and form.is_valid():
        try:
            apply_admin_pricing(
                product=product,
                profit_margin_type=form.cleaned_data["profit_margin_type"],
                profit_margin=form.cleaned_data["profit_margin"],
                discount_type=form.cleaned_data.get("discount_type") or "",
                discount_value=form.cleaned_data.get("discount_value"),
                changed_by=request.user,
                reason=form.cleaned_data.get("reason", ""),
                request=request,
            )
        except ValidationError as exc:
            if hasattr(exc, "message_dict"):
                for field, errors in exc.message_dict.items():
                    for error in errors:
                        form.add_error(
                            field if field in form.fields else None,
                            error,
                        )
            else:
                messages.error(request, str(exc))
        else:
            messages.success(request, "Product pricing updated.")
            return redirect("catalog:product_detail", pk=product.pk)

    selling_preview = product.selling_price
    final_preview = product.final_price
    if form.is_bound and hasattr(form, "cleaned_data"):
        selling_preview = form.cleaned_data.get(
            "selling_price_preview", selling_preview
        )
        final_preview = form.cleaned_data.get("final_price_preview", final_preview)

    return render(
        request,
        "management/products/pricing.html",
        {
            "product": product,
            "form": form,
            "selling_price_preview": selling_preview,
            "final_price_preview": final_preview,
        },
    )


@catalog_permission_required("catalog.view_product")
def product_change_status_view(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    product = _get_product_or_404(pk)
    available = _management_available_transitions(request.user, product)
    form = ProductStatusChangeForm(
        request.POST,
        current_status=product.status,
        allowed_statuses=available,
    )
    if not form.is_valid():
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
        return redirect("catalog:product_detail", pk=product.pk)

    new_status = form.cleaned_data["new_status"]
    required = permission_for_transition(product.status, new_status)
    if not required or not user_has_catalog_permission(request.user, required):
        raise PermissionDenied(
            "You do not have permission to set that product status."
        )

    try:
        record_product_status_change(
            product=product,
            new_status=new_status,
            changed_by=request.user,
            reason=form.cleaned_data.get("reason", ""),
            request=request,
            actor_is_store_user=False,
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("catalog:product_detail", pk=product.pk)

    messages.success(request, f"Product status changed to {new_status}.")
    return redirect("catalog:product_detail", pk=product.pk)


@catalog_permission_required("catalog.change_product")
@image_request_errors
def product_images_view(request, pk):
    product = _get_product_or_404(pk)
    image_count = product.images.count()
    form = ProductImageForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if form.is_valid():
            try:
                add_product_image(
                    product=product,
                    changed_by=request.user, request=request,
                    image=form.cleaned_data["image"],
                    alt_text=form.cleaned_data.get("alt_text", ""),
                    sort_order=form.cleaned_data.get("sort_order") or 0,
                    is_primary=form.cleaned_data.get("is_primary", False),
                )
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, "Image added.")
                return redirect("catalog:product_images", pk=product.pk)
        else:
            messages.error(
                request, "Could not add image. Check the file and try again."
            )
    return render(
        request,
        "management/products/images.html",
        {
            "product": product,
            "form": form,
            "image_count": image_count,
            "max_images": MAX_IMAGES_PER_PRODUCT,
            "can_add_image": image_count < MAX_IMAGES_PER_PRODUCT,
        },
    )


@catalog_permission_required("catalog.change_product")
@image_request_errors
def product_image_delete_view(request, pk, image_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    product = _get_product_or_404(pk)
    try:
        delete_product_image(product=product, image_id=image_id, changed_by=request.user, request=request)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("catalog:product_images", pk=product.pk)
    messages.success(request, "Image removed.")
    return redirect("catalog:product_images", pk=product.pk)


@catalog_permission_required("catalog.change_product")
@image_request_errors
def product_image_set_primary_view(request, pk, image_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    product = _get_product_or_404(pk)
    set_primary_product_image(product=product, image_id=image_id)
    messages.success(request, "Primary image updated.")
    return redirect("catalog:product_images", pk=product.pk)


# ----- Management: taxonomy -----


@catalog_permission_required("catalog.view_productcategory")
def category_list_view(request):
    categories = ProductCategory.objects.select_related("parent").order_by("name")
    return render(
        request,
        "management/products/categories_list.html",
        {
            "categories": categories,
            "can_add": user_has_catalog_permission(
                request.user, "catalog.add_productcategory"
            ),
            "can_change": user_has_catalog_permission(
                request.user, "catalog.change_productcategory"
            ),
        },
    )


@catalog_permission_required("catalog.add_productcategory")
def category_create_view(request):
    form = ProductCategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        category = form.save()
        messages.success(request, f"Category '{category.name}' created.")
        return redirect("catalog:category_list")
    return render(
        request,
        "management/products/category_form.html",
        {"form": form, "title": "Create category"},
    )


@catalog_permission_required("catalog.change_productcategory")
def category_edit_view(request, pk):
    category = get_object_or_404(ProductCategory, pk=pk)
    form = ProductCategoryForm(request.POST or None, instance=category)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Category updated.")
        return redirect("catalog:category_list")
    return render(
        request,
        "management/products/category_form.html",
        {"form": form, "title": "Edit category", "category": category},
    )


@catalog_permission_required("catalog.view_brand")
def brand_list_view(request):
    brands = Brand.objects.order_by("name")
    return render(
        request,
        "management/products/brands_list.html",
        {
            "brands": brands,
            "can_add": user_has_catalog_permission(request.user, "catalog.add_brand"),
            "can_change": user_has_catalog_permission(
                request.user, "catalog.change_brand"
            ),
        },
    )


@catalog_permission_required("catalog.add_brand")
def brand_create_view(request):
    form = BrandForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        brand = form.save()
        messages.success(request, f"Brand '{brand.name}' created.")
        return redirect("catalog:brand_list")
    return render(
        request,
        "management/products/brand_form.html",
        {"form": form, "title": "Create brand"},
    )


@catalog_permission_required("catalog.change_brand")
def brand_edit_view(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    form = BrandForm(request.POST or None, instance=brand)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Brand updated.")
        return redirect("catalog:brand_list")
    return render(
        request,
        "management/products/brand_form.html",
        {"form": form, "title": "Edit brand", "brand": brand},
    )


@catalog_permission_required("catalog.view_tag")
def tag_list_view(request):
    tags = Tag.objects.order_by("name")
    return render(
        request,
        "management/products/tags_list.html",
        {
            "tags": tags,
            "can_add": user_has_catalog_permission(request.user, "catalog.add_tag"),
            "can_change": user_has_catalog_permission(
                request.user, "catalog.change_tag"
            ),
        },
    )


@catalog_permission_required("catalog.add_tag")
def tag_create_view(request):
    form = TagForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        tag = form.save()
        messages.success(request, f"Tag '{tag.name}' created.")
        return redirect("catalog:tag_list")
    return render(
        request,
        "management/products/tag_form.html",
        {"form": form, "title": "Create tag"},
    )


@catalog_permission_required("catalog.change_tag")
def tag_edit_view(request, pk):
    tag = get_object_or_404(Tag, pk=pk)
    form = TagForm(request.POST or None, instance=tag)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Tag updated.")
        return redirect("catalog:tag_list")
    return render(
        request,
        "management/products/tag_form.html",
        {"form": form, "title": "Edit tag", "tag": tag},
    )


# ----- Store portal -----


@store_portal_required
def store_product_list_view(request):
    primary_images = Prefetch(
        "images",
        queryset=ProductImage.objects.filter(is_primary=True),
        to_attr="primary_image_list",
    )
    queryset = (
        portal_products_queryset(request)
        .prefetch_related(primary_images)
        .order_by("-created_at")
    )
    search_query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    category_filter = request.GET.get("category", "").strip()
    brand_filter = request.GET.get("brand", "").strip()
    stock_filter = request.GET.get("stock", "").strip()

    if search_query:
        queryset = queryset.filter(
            Q(name__icontains=search_query)
            | Q(sku__icontains=search_query)
            | Q(product_code__icontains=search_query)
        )
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    if category_filter:
        queryset = queryset.filter(category_id=category_filter)
    if brand_filter:
        queryset = queryset.filter(brand_id=brand_filter)
    if stock_filter == "in_stock":
        queryset = queryset.filter(stock_quantity__gt=0)
    elif stock_filter == "out_of_stock":
        queryset = queryset.filter(stock_quantity__lte=0)
    elif stock_filter == "low_stock":
        queryset = queryset.filter(
            stock_quantity__gt=0,
            stock_quantity__lte=F("low_stock_threshold"),
        )

    page_obj = Paginator(queryset, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "store_portal/products/list.html",
        {
            "page_obj": page_obj,
            "search_query": search_query,
            "status_filter": status_filter,
            "category_filter": category_filter,
            "brand_filter": brand_filter,
            "stock_filter": stock_filter,
            "status_choices": ProductStatus.choices,
            "categories": ProductCategory.objects.filter(is_active=True).order_by(
                "name"
            ),
            "brands": Brand.objects.filter(is_active=True).order_by("name"),
        },
    )


@store_portal_required
def store_product_detail_view(request, pk):
    product = get_portal_product_or_404(request, pk)
    can_edit = product.status in {
        ProductStatus.DRAFT,
        ProductStatus.PENDING,
        ProductStatus.REJECTED,
        ProductStatus.APPROVED,
    }
    can_submit = product.status == ProductStatus.DRAFT
    return render(
        request,
        "store_portal/products/detail.html",
        {
            "product": product,
            "can_edit": can_edit,
            "can_submit": can_submit,
        },
    )


@store_portal_required
@image_request_errors
def store_product_create_view(request):
    # Always pass POST/FILES objects when bound — never use `or None` on
    # MultiValueDict (empty dicts are falsy and break file handling).
    if request.method == "POST":
        form = StoreProductCreateForm(request.POST, request.FILES)
    else:
        form = StoreProductCreateForm()
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        save_as_draft = data.pop("save_as_draft", False)
        tags = data.pop("tags", [])
        images = data.pop("images", [])
        # Never accept management-only or foreign-store fields from the portal.
        for blocked in (
            "store",
            "store_id",
            "profit_margin_type",
            "profit_margin",
            "selling_price",
            "discount_type",
            "discount_value",
            "final_price",
            "status",
            "is_featured",
            "is_active",
            "rejection_reason",
            "product_code",
        ):
            data.pop(blocked, None)
        initial_status = (
            ProductStatus.DRAFT if save_as_draft else ProductStatus.PENDING
        )
        product = create_product(
            store=request.store,
            product_data=data,
            created_by=request.user,
            tag_ids=[t.pk for t in tags],
            images=images,
            initial_status=initial_status,
            request=request,
        )
        messages.success(
            request,
            f"Product {product.product_code} created.",
        )
        return redirect("catalog:store_product_detail", pk=product.pk)

    return render(
        request,
        "store_portal/products/create.html",
        {"form": form},
    )


@store_portal_required
def store_product_edit_view(request, pk):
    product = get_portal_product_or_404(request, pk)
    if product.status == ProductStatus.INACTIVE:
        messages.error(
            request,
            "Inactive products cannot be edited from the store portal.",
        )
        return redirect("catalog:store_product_detail", pk=product.pk)

    form = StoreProductForm(
        request.POST or None,
        request.FILES or None,
        instance=product,
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        tags = data.pop("tags", [])
        for blocked in (
            "store",
            "store_id",
            "profit_margin_type",
            "profit_margin",
            "selling_price",
            "discount_type",
            "discount_value",
            "final_price",
            "status",
            "is_featured",
            "is_active",
            "rejection_reason",
            "product_code",
        ):
            data.pop(blocked, None)
        update_product(
            product=product,
            product_data=data,
            updated_by=request.user,
            tag_ids=[t.pk for t in tags],
            request=request,
            actor_is_store_user=True,
        )
        messages.success(request, "Product updated.")
        return redirect("catalog:store_product_detail", pk=product.pk)

    return render(
        request,
        "store_portal/products/edit.html",
        {"product": product, "form": form},
    )


@store_portal_required
def store_product_submit_view(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    product = get_portal_product_or_404(request, pk)
    try:
        record_product_status_change(
            product=product,
            new_status=ProductStatus.PENDING,
            changed_by=request.user,
            reason="Submitted for approval",
            request=request,
            actor_is_store_user=True,
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("catalog:store_product_detail", pk=product.pk)
    messages.success(request, "Product submitted for approval.")
    return redirect("catalog:store_product_detail", pk=product.pk)


@store_portal_required
@image_request_errors
def store_product_images_view(request, pk):
    product = get_portal_product_or_404(request, pk)
    image_count = product.images.count()
    form = ProductImageForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if form.is_valid():
            try:
                add_product_image(
                    product=product,
                    changed_by=request.user, request=request,
                    image=form.cleaned_data["image"],
                    alt_text=form.cleaned_data.get("alt_text", ""),
                    sort_order=form.cleaned_data.get("sort_order") or 0,
                    is_primary=form.cleaned_data.get("is_primary", False),
                )
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, "Image added.")
                return redirect("catalog:store_product_images", pk=product.pk)
        else:
            messages.error(request, "Could not add image.")
    return render(
        request,
        "store_portal/products/images.html",
        {
            "product": product,
            "form": form,
            "image_count": image_count,
            "max_images": MAX_IMAGES_PER_PRODUCT,
            "can_add_image": image_count < MAX_IMAGES_PER_PRODUCT,
        },
    )


@store_portal_required
@image_request_errors
def store_product_image_delete_view(request, pk, image_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    product = get_portal_product_or_404(request, pk)
    try:
        delete_product_image(product=product, image_id=image_id, changed_by=request.user, request=request)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("catalog:store_product_images", pk=product.pk)
    messages.success(request, "Image removed.")
    return redirect("catalog:store_product_images", pk=product.pk)


@store_portal_required
@image_request_errors
def store_product_image_set_primary_view(request, pk, image_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    product = get_portal_product_or_404(request, pk)
    set_primary_product_image(product=product, image_id=image_id)
    messages.success(request, "Primary image updated.")
    return redirect("catalog:store_product_images", pk=product.pk)
