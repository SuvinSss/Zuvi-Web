"""Downloadable import error reports (cells are neutralised against formula injection)."""
import csv
import io

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font

HEADER = ["row", "sku", "column", "error"]


def safe(value):
    """Prefix spreadsheet-formula starters so Excel treats the cell as text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _rows(batch):
    return [[error.get("row"), safe(error.get("sku")), error.get("column", ""), safe(error.get("message"))]
            for error in batch.errors]


def csv_response(batch):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(HEADER)
    writer.writerows(_rows(batch))
    response = HttpResponse(out.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="import-errors-{batch.pk}.csv"'
    return response


def xlsx_response(batch):
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Errors"
    sheet.append(HEADER)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in _rows(batch):
        sheet.append(row)
    sheet.column_dimensions["B"].width = 20
    sheet.column_dimensions["D"].width = 80
    out = io.BytesIO()
    wb.save(out)
    response = HttpResponse(
        out.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="import-errors-{batch.pk}.xlsx"'
    return response
