from django.core.exceptions import MultipleObjectsReturned
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from accounts.models import Role

from .models import Brand, ProductCategory
from .public import (
    PUBLIC_PAGE_SIZE,
    apply_public_filters,
    apply_public_search,
    apply_public_sort,
    get_public_product_by_slug,
    public_categories_queryset,
    public_product_card,
    public_product_detail_context,
    public_products_queryset,
)
from .public_forms import PublicAddToCartForm, PublicProductFilterForm


def _remove_params_querystring(request, *names):
    qs = request.GET.copy()
    qs.pop("page", None)
    for name in names:
        qs.pop(name, None)
    return qs.urlencode()


def _active_filter_chips(request, data, *, brands):
    chips = []
    if data.get("q"):
        chips.append(
            {
                "label": f"“{data['q']}”",
                "remove_querystring": _remove_params_querystring(request, "q"),
            }
        )
    if data.get("brand"):
        brand_name = next(
            (brand.name for brand in brands if brand.slug == data["brand"]),
            data["brand"],
        )
        chips.append(
            {
                "label": brand_name,
                "remove_querystring": _remove_params_querystring(request, "brand"),
            }
        )
    min_price = data.get("min_price")
    max_price = data.get("max_price")
    if min_price or max_price:
        if min_price and max_price:
            label = f"₹{min_price}–₹{max_price}"
        elif min_price:
            label = f"Above ₹{min_price}"
        else:
            label = f"Under ₹{max_price}"
        chips.append(
            {
                "label": label,
                "remove_querystring": _remove_params_querystring(
                    request, "min_price", "max_price"
                ),
            }
        )
    return chips


def _list_context(request, *, queryset, page_title, active_category=None):
    form = PublicProductFilterForm(request.GET or None)
    if form.is_valid():
        data = form.cleaned_data
    else:
        data = {
            "q": request.GET.get("q", ""),
            "category": request.GET.get("category", ""),
            "brand": request.GET.get("brand", ""),
            "min_price": request.GET.get("min_price") or None,
            "max_price": request.GET.get("max_price") or None,
            "sort": request.GET.get("sort") or "newest",
        }

    category_slug = data.get("category") or (
        active_category.slug if active_category else ""
    )
    queryset = apply_public_search(queryset, data.get("q"))
    queryset = apply_public_filters(
        queryset,
        category_slug=category_slug,
        brand_slug=data.get("brand"),
        min_price=data.get("min_price"),
        max_price=data.get("max_price"),
    )
    queryset = apply_public_sort(queryset, data.get("sort"))

    paginator = Paginator(queryset, PUBLIC_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    products = [public_product_card(product) for product in page_obj.object_list]

    query = request.GET.copy()
    query.pop("page", None)

    brands = list(Brand.objects.filter(is_active=True).order_by("name"))

    return {
        "page_title": page_title,
        "filter_form": form,
        "products": products,
        "page_obj": page_obj,
        "paginator": paginator,
        "querystring": query.urlencode(),
        "categories": public_categories_queryset(),
        "brands": brands,
        "active_category": active_category,
        "active_category_slug": category_slug,
        "active_filters": _active_filter_chips(request, data, brands=brands),
        "active_sort": data.get("sort") or "newest",
        "result_count": paginator.count,
    }


def public_home_view(request):
    queryset = public_products_queryset()
    featured = [
        public_product_card(product)
        for product in queryset.filter(is_featured=True).order_by("-updated_at", "pk")[
            :8
        ]
    ]
    newest = [
        public_product_card(product)
        for product in queryset.order_by("-created_at", "pk")[:8]
    ]
    return render(
        request,
        "public/home.html",
        {
            "page_title": "ZuuVi",
            "featured_products": featured,
            "newest_products": newest,
            "categories": public_categories_queryset()[:12],
        },
    )


def public_product_list_view(request):
    context = _list_context(
        request,
        queryset=public_products_queryset(),
        page_title="Products",
    )
    return render(request, "public/product_list.html", context)


def public_product_detail_view(request, slug):
    try:
        product = get_public_product_by_slug(slug)
    except MultipleObjectsReturned as exc:
        raise Http404("Product not found.") from exc

    detail = public_product_detail_context(product)
    add_form = PublicAddToCartForm(initial={"quantity": "1.000"})
    return render(
        request,
        "public/product_detail.html",
        {
            "page_title": detail["name"],
            "product": detail,
            "add_to_cart_form": add_form,
            "can_add_to_cart": (
                request.user.is_authenticated
                and getattr(request.user, "role", None) == Role.CUSTOMER
            ),
        },
    )


def public_category_detail_view(request, slug):
    category = get_object_or_404(
        ProductCategory.objects.filter(is_active=True),
        slug=slug,
    )
    queryset = public_products_queryset().filter(category=category)
    context = _list_context(
        request,
        queryset=queryset,
        page_title=category.name,
        active_category=category,
    )
    if "category" in context["filter_form"].fields:
        context["filter_form"].fields["category"].initial = category.slug
    return render(request, "public/product_list.html", context)
