"""CSV v1: bounded, deterministic input; no product mutations or remote I/O."""
import csv
import hashlib
import io
import json
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from .models import Brand, ProductCategory, ProductUnit, Tag
from .pricing import calculate_prices

VERSION = 'v1'
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_ROWS = 1000
HEADERS = ('store_code external_sku name description category_path brand_slug tag_slugs unit unit_value store_price profit_margin_type profit_margin discount_type discount_value manufacturing_date expiry_date low_stock_threshold image_1 image_2 image_3 image_4 image_5 primary_image_index opening_stock opening_stock_reason').split()
PRICING_FIELDS = ('profit_margin_type', 'profit_margin', 'discount_type', 'discount_value')


class ImportProblem(Exception):
    def __init__(self, code, message, field=''):
        self.code, self.message, self.field = code, message, field
        super().__init__(message)

    def as_error(self):
        return {'code': self.code, 'field': self.field, 'message': self.message}


def digest(value):
    return hashlib.sha256(value).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8'))


def safe_cell(value):
    value = '' if value is None else str(value)
    if value.lstrip().startswith(('=', '+', '-', '@')) or any(c in value for c in '\t\r\n'):
        return "'" + value
    return value


def csv_text(rows):
    out = io.StringIO(newline='')
    writer = csv.writer(out, lineterminator='\n')
    writer.writerows([[safe_cell(cell) for cell in row] for row in rows])
    return out.getvalue()


def decimal_value(text, field, places, *, required=False, positive=False, default=None):
    if not text:
        if required:
            raise ImportProblem('REQUIRED', 'A value is required.', field)
        return default
    try:
        value = Decimal(text)
        if not value.is_finite() or value < 0 or (positive and value <= 0):
            raise ValueError
        # Reject exponent notation/grouping and excess precision instead of rounding intent.
        if any(c not in '0123456789.' for c in text) or text.count('.') > 1:
            raise ValueError
        if value.as_tuple().exponent < -places or value >= Decimal(10) ** (12 - places):
            raise ValueError
        return format(value.quantize(Decimal(1).scaleb(-places)), 'f')
    except (InvalidOperation, ValueError):
        raise ImportProblem('DECIMAL', f'Use a {"positive" if positive else "non-negative"} number with at most {places} decimal places and 12 total digits.', field)


def reference_catalogue():
    categories = {c.pk: c for c in ProductCategory.objects.all()}
    paths = {}
    for c in categories.values():
        if not c.is_active:
            continue
        current, chain, seen = c, [], set()
        while current and current.pk not in seen:
            seen.add(current.pk)
            chain.append({'id': current.pk, 'name': current.name, 'parent_id': current.parent_id})
            current = categories.get(current.parent_id)
        if current is not None:
            continue
        chain.reverse()
        path = ' / '.join(node['name'] for node in chain)
        paths.setdefault(path, []).append({'id': c.pk, 'path': path, 'chain': chain})
    brands = {b.slug: {'id': b.pk, 'slug': b.slug, 'name': b.name} for b in Brand.objects.filter(is_active=True)}
    tags = {t.slug: {'id': t.pk, 'slug': t.slug, 'name': t.name} for t in Tag.objects.filter(is_active=True)}
    return paths, brands, tags


def normalize(raw, store, refs):
    from .import_files import validate_filename
    paths, brands, tags = refs
    data = {key: raw[key].strip() for key in HEADERS}
    for key in ('store_code', 'external_sku', 'name', 'category_path', 'unit', 'unit_value', 'store_price'):
        if not data[key]:
            raise ImportProblem('REQUIRED', 'A value is required.', key)
    if data['store_code'] != store.store_code:
        raise ImportProblem('STORE_MISMATCH', 'Store code must match the selected authorized store.', 'store_code')
    for key, limit in [('external_sku', 64), ('name', 200), ('opening_stock_reason', 500)]:
        if len(data[key]) > limit:
            raise ImportProblem('TOO_LONG', f'Use at most {limit} characters.', key)
    matches = paths.get(data['category_path'], [])
    if len(matches) != 1:
        raise ImportProblem('CATEGORY', 'Use one exact existing active category path.', 'category_path')
    data['category'] = matches[0]
    data['brand'] = None
    if data['brand_slug']:
        if data['brand_slug'] not in brands:
            raise ImportProblem('BRAND', 'Use an existing active brand slug.', 'brand_slug')
        data['brand'] = brands[data['brand_slug']]
    tag_names = data['tag_slugs'].split('|') if data['tag_slugs'] else []
    if len(set(tag_names)) != len(tag_names) or any(t not in tags for t in tag_names):
        raise ImportProblem('TAGS', 'Use distinct existing active tag slugs separated by |.', 'tag_slugs')
    data['tags'] = [tags[t] for t in sorted(tag_names)]
    if data['unit'] not in ProductUnit.values:
        raise ImportProblem('UNIT', 'Choose a supported unit from the instructions.', 'unit')
    for key, places, required, positive, default in [
        ('unit_value', 3, True, False, None), ('store_price', 2, True, False, None),
        ('low_stock_threshold', 3, False, False, '0.000'), ('opening_stock', 3, False, True, None),
        ('profit_margin', 2, False, False, None), ('discount_value', 2, False, False, None),
    ]:
        data[key] = decimal_value(data[key], key, places, required=required, positive=positive, default=default)
    if bool(data['opening_stock']) != bool(data['opening_stock_reason']):
        raise ImportProblem('OPENING_PAIR', 'Supply both a positive opening quantity and a reason, or leave both blank.', 'opening_stock')
    if any(raw[k].strip() for k in PRICING_FIELDS):
        if data['profit_margin_type'] not in ('FIXED', 'PERCENTAGE') or data['profit_margin'] is None:
            raise ImportProblem('PRICING', 'Supply both a supported margin type and value.', 'profit_margin_type')
        if bool(data['discount_type']) != (data['discount_value'] is not None):
            raise ImportProblem('PRICING', 'Supply both discount type and value, or leave both blank.', 'discount_type')
        try:
            selling, final = calculate_prices(store_price=Decimal(data['store_price']), profit_margin_type=data['profit_margin_type'], profit_margin=Decimal(data['profit_margin']), discount_type=data['discount_type'], discount_value=Decimal(data['discount_value'] or '0'))
        except ValidationError:
            raise ImportProblem('PRICING', 'Pricing does not meet the existing margin, discount or final-price rules.', 'profit_margin')
        data['price_preview'] = {'selling_price': str(selling), 'final_price': str(final)}
    else:
        data['price_preview'] = None
    for key in ('manufacturing_date', 'expiry_date'):
        if data[key]:
            try:
                parsed = date.fromisoformat(data[key])
                if parsed.isoformat() != data[key]:
                    raise ValueError
            except ValueError:
                raise ImportProblem('DATE', 'Use an ISO YYYY-MM-DD date.', key)
        else:
            data[key] = None
    if data['manufacturing_date'] and data['expiry_date'] and data['expiry_date'] < data['manufacturing_date']:
        raise ImportProblem('DATE_ORDER', 'Expiry must be on or after manufacture.', 'expiry_date')
    filenames = [data[f'image_{i}'] for i in range(1, 6)]
    images = [name for name in filenames if name]
    if filenames[:len(images)] != images or len(set(images)) != len(images):
        raise ImportProblem('IMAGE_ORDER', 'List distinct filenames contiguously from image_1.', 'image_1')
    for name in images:
        validate_filename(name)
    primary = data['primary_image_index']
    if (not images and primary) or (primary and (not primary.isdigit() or not 1 <= int(primary) <= len(images))):
        raise ImportProblem('PRIMARY', 'Primary index must identify a supplied image; leave blank without images.', 'primary_image_index')
    data['primary_image_index'] = int(primary) if primary else (1 if images else None)
    data['images'] = [{'filename': name} for name in images]
    return data


def parse_csv(content, store):
    if not content or len(content) > MAX_CSV_BYTES:
        raise ImportProblem('CSV_SIZE', 'Upload a nonempty UTF-8 CSV no larger than 5 MiB.')
    try:
        text = content.decode('utf-8-sig')
        if '\x00' in text:
            raise ValueError
        reader = csv.reader(io.StringIO(text, newline=''), strict=True)
        if next(reader, None) != HEADERS:
            raise ImportProblem('HEADERS', 'Use all 25 template headers in their exact order.')
        raw_rows = []
        for values in reader:
            if len(raw_rows) >= MAX_ROWS:
                raise ImportProblem('ROW_LIMIT', 'Use at most 1,000 data rows per job.')
            if len(values) != len(HEADERS) or any(len(v) > 100_000 for v in values):
                raise ImportProblem('CSV_RECORD', 'Every record must have 25 values, each at most 100,000 characters.')
            raw_rows.append(dict(zip(HEADERS, values)))
    except (UnicodeError, csv.Error, ValueError):
        raise ImportProblem('CSV_FORMAT', 'Use valid UTF-8 CSV with correctly quoted values and no NUL characters.')
    if not raw_rows:
        raise ImportProblem('EMPTY_CSV', 'Add at least one data row below the header.')
    refs = reference_catalogue()
    duplicate_skus = {k for k, n in Counter(row['external_sku'].strip() for row in raw_rows).items() if n > 1}
    rows = []
    for number, raw in enumerate(raw_rows, 1):
        data, errors = {}, []
        try:
            data = normalize(raw, store, refs)
            if data['external_sku'] in duplicate_skus:
                raise ImportProblem('DUPLICATE_SKU', 'This source SKU occurs more than once in this CSV.', 'external_sku')
        except ImportProblem as exc:
            errors = [exc.as_error()]
        rows.append({'row_number': number, 'payload': {'raw': raw, 'data': data}, 'errors': errors, 'external_sku': data.get('external_sku') if not errors else None})
    return rows


def bind_images(data, manifest):
    data = json.loads(json.dumps(data))
    data['images'] = [dict(filename=image['filename'], **manifest[image['filename']]) for image in data['images']]
    hashes = [image['sha256'] for image in data['images']]
    if len(hashes) != len(set(hashes)):
        raise ImportProblem('DUPLICATE_IMAGE', 'The same image content appears twice in one product.', 'image_1')
    return data
