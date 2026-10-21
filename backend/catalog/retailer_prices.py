"""Read public Shopify product offers from explicitly supported Indian shops.

No API key, paid provider, arbitrary hosts, redirects, or authenticated sessions.
Product identity is still verified by the administrator against their photos.
"""

import json
import re
from decimal import Decimal
from urllib.parse import urlsplit, parse_qs

import requests
from django.core.exceptions import ValidationError
from django.utils import timezone

RETAILERS = frozenset(
    {"truewholesale.in", "tintandshade.in", "deodap.in", "www.mangostationery.com"}
)


def read_json(session, url):
    with session.get(
        url, timeout=(4, 8), allow_redirects=False, stream=True
    ) as response:
        if response.status_code != 200:
            raise ValidationError(
                "This retailer could not provide a current offer. Review its product page manually."
            )
        chunks = []
        size = 0
        for chunk in response.iter_content(16384):
            size += len(chunk)
            if size > 1024 * 1024:
                raise ValidationError("Retailer response is too large.")
            chunks.append(chunk)
        data = json.loads(b"".join(chunks))
        if not isinstance(data, dict):
            raise ValidationError("Invalid retailer response.")
        return data


def fetch_offer(url):
    try:
        parsed = urlsplit(str(url))
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or host not in RETAILERS
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ValidationError(
                "Automatic price reading supports TrueWholesale, Tint & Shade, DeoDap and Mango Stationery product links. Other retailers can be entered manually."
            )
        match = re.fullmatch(
            r"(?:/collections/[a-zA-Z0-9-]+)?/products/([a-zA-Z0-9-]+)/?", parsed.path
        )
        if not match:
            raise ValidationError("Use a retailer product page URL.")
        clean = f"https://{host}/products/{match.group(1)}"
        with requests.Session() as session:
            session.headers.update(
                {"User-Agent": "ZuuViCatalogue/1.0", "Accept": "application/json"}
            )
            # Shopify reports prices in presentment currency, which must be checked.
            if read_json(session, f"https://{host}/cart.js").get("currency") != "INR":
                raise ValidationError("The retailer did not return INR prices.")
            product = read_json(session, clean + ".js")
        variants = product.get("variants", [])
        if not isinstance(variants, list) or not variants:
            raise ValidationError("No retailer variant could be read.")
        selected = parse_qs(parsed.query).get("variant", [""])[0]
        if selected:
            variants = [v for v in variants if str(v.get("id")) == selected]
        if len(variants) != 1:
            raise ValidationError(
                "Choose the exact size/colour on the retailer page and paste its link with a variant ID."
            )
        variant = variants[0]
        if variant.get("available") is not True:
            raise ValidationError(
                "This retailer variant is out of stock; exclude it from the average."
            )
        price = variant.get("price")
        if type(price) is not int or not 0 < price < 100000000000:
            raise ValidationError("No valid retailer price could be read.")
        return {
            "url": clean + ("?variant=" + str(variant["id"]) if selected else ""),
            "title": str(product.get("title", ""))[:300],
            "variant": str(variant.get("title", ""))[:200],
            "price": str((Decimal(price) / 100).quantize(Decimal(".01"))),
            "currency": "INR",
            "availability": "in_stock",
            "checked_at": timezone.localdate().isoformat(),
            "tax_shipping": "Shipping excluded. Confirm tax treatment on source page.",
            "exact_match": False,
        }
    except (requests.RequestException, ValueError, TypeError, KeyError):
        raise ValidationError(
            "Could not read this retailer. Open the source page and enter the price manually."
        )
