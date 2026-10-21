"""Intelligent import: header aliases, manual mapping, classification, safe clean-ups, corrections, retry."""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.urls import reverse

from .models import Product, ProductImportBatch
from .tests_import import ImportBase, workbook_bytes

User = get_user_model()
ALIAS_HEADER = ["Product Name", "Item Code", "Category", "Selling Price", "Shop Code", "Stock", "Weird Column"]


def alias_rows(store, **over):
    row = {"Product Name": "Basmati Rice", "Item Code": "BAS-1", "Category": "Groceries", "Selling Price": "99.50",
           "Shop Code": store.store_code, "Stock": "40", "Weird Column": "x"}
    row.update(over)
    return row


class SmartImportBase(ImportBase):
    def api(self, method, name, *args, body=None, **query):
        url = reverse(name, args=args)
        if method == "patch":
            return self.client.patch(url, json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=self.token)
        if method == "post":
            return self.client.post(url, HTTP_X_CSRFTOKEN=self.token)
        return self.client.get(url, query)


class AliasAndMappingTests(SmartImportBase):
    def test_common_header_names_are_recognised_without_a_template(self):
        r = self.preview([alias_rows(self.store)], content=workbook_bytes([alias_rows(self.store)], ALIAS_HEADER))
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["counts"]["valid"], 1)
        self.assertEqual(body["rows"][0]["values"]["name"], "Basmati Rice")
        self.assertIn("Stock", body["ignored_columns"])  # stock is never written by an import
        self.assertIn("Weird Column", body["ignored_columns"])

    def test_unrecognised_required_column_returns_mapping_screen_data(self):
        header = ["Title", "Zzz", "Department", "Price", "Outlet"]
        row = {"Title": "Rice", "Zzz": "R1", "Department": "Groceries", "Price": "10", "Outlet": self.store.store_code}
        r = self.preview([row], content=workbook_bytes([row], header), name="odd.xlsx")
        self.assertEqual(r.status_code, 422)
        info = r.json()
        self.assertTrue(info["needs_mapping"])
        self.assertEqual(info["missing_required"], ["sku"])
        self.assertIn({"source": "Zzz", "key": None, "how": None}, info["proposal"])
        self.assertEqual(ProductImportBatch.objects.count(), 0)  # nothing staged yet
        again = self.preview([row], content=workbook_bytes([row], header), name="odd.xlsx", mapping=json.dumps({"Zzz": "sku"}))
        self.assertEqual(again.status_code, 201, again.content)
        self.assertEqual(again.json()["rows"][0]["sku"], "R1")

    def test_bad_mapping_json_is_rejected(self):
        r = self.preview([self.row()], mapping="not json")
        self.assertEqual(r.status_code, 400)
        r = self.preview([self.row()], mapping=json.dumps({"a": 1}))
        self.assertEqual(r.status_code, 400)

    def test_store_can_be_chosen_on_screen_when_file_has_no_store_column(self):
        header = ["name", "sku", "category", "store_price"]
        row = {"name": "Rice", "sku": "S1", "category": "Groceries", "store_price": "5"}
        content = workbook_bytes([row], header)
        self.assertEqual(self.preview([row], content=content).status_code, 422)
        ok = self.preview([row], content=content, default_store_code=self.store.store_code)
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertEqual(ok.json()["counts"]["valid"], 1)
        bad = self.preview([row], content=content, default_store_code="NOPE")
        self.assertEqual(bad.json()["rows"][0]["status"], "incomplete")  # unknown store is recoverable, not invalid


class ClassificationAndCleanupTests(SmartImportBase):
    def test_rows_are_classified_valid_incomplete_invalid(self):
        rows = [self.row(), self.row(sku="NOCAT", category=None), self.row(sku="NOPRICE", store_price=None),
                self.row(sku="BADPRICE", store_price="abc")]
        body = self.preview(rows, all_or_nothing="false").json()
        kinds = {r["sku"]: r["status"] for r in body["rows"]}
        self.assertEqual(kinds, {"RICE-1": "valid", "NOCAT": "incomplete", "NOPRICE": "incomplete", "BADPRICE": "invalid"})
        self.assertEqual((body["counts"]["incomplete"], body["counts"]["hard_invalid"]), (2, 1))

    def test_missing_sku_is_generated_flagged_and_stored_on_the_product(self):
        body = self.preview([self.row(sku=None, name="Red Rice 1kg")]).json()
        row = body["rows"][0]
        self.assertEqual(row["generated"], ["sku"])
        self.assertEqual(row["sku"], "AUTO-RED-RICE-1KG")
        self.assertEqual(self.commit(body["id"]).status_code, 200)
        product = Product.objects.get()
        self.assertEqual(product.generated_fields, ["sku"])
        self.assertEqual(product.import_batch_id.hex, body["id"].replace("-", ""))

    def test_sku_generation_can_be_switched_off(self):
        body = self.preview([self.row(sku=None)], generate_sku="false").json()
        self.assertEqual(body["rows"][0]["status"], "incomplete")

    def test_currency_symbols_are_cleaned_but_never_rounded_or_invented(self):
        body = self.preview([self.row(store_price="₹ 1,250.50"), self.row(sku="R3", store_price="10.555")], all_or_nothing="false").json()
        clean, rounded = body["rows"]
        self.assertEqual(clean["status"], "valid")
        self.assertEqual(clean["normalized"]["store_price"], ["₹ 1,250.50", "1,250.50"])
        self.assertEqual(rounded["status"], "invalid")  # 3 decimals is an error, not silently rounded
        self.assertEqual(self.commit(body["id"]).status_code, 200)
        self.assertEqual(str(Product.objects.get(sku="RICE-1").store_price), "1250.50")


class CorrectionAndRetryTests(SmartImportBase):
    def test_row_correction_fixes_an_incomplete_row_then_commit_imports_it(self):
        body = self.preview([self.row(store_price=None)]).json()
        self.assertEqual(body["rows"][0]["status"], "incomplete")
        self.assertEqual(self.commit(body["id"]).status_code, 409)  # strict mode: nothing imported
        fixed = self.api("patch", "api_import_row", body["id"], 2, body={"values": {"store_price": "45.00"}})
        self.assertEqual(fixed.status_code, 200, fixed.content)
        self.assertEqual(fixed.json()["row"]["status"], "valid")
        self.assertEqual(fixed.json()["counts"]["incomplete"], 0)
        self.assertEqual(self.commit(body["id"]).status_code, 200)
        self.assertEqual(str(Product.objects.get().store_price), "45.00")

    def test_corrections_are_validated_and_restricted(self):
        body = self.preview([self.row()]).json()
        for payload in ({"values": {"store_price": "x"}}, ):
            r = self.api("patch", "api_import_row", body["id"], 2, body=payload)
            self.assertEqual(r.json()["row"]["status"], "invalid")
        self.assertEqual(self.api("patch", "api_import_row", body["id"], 2, body={"values": {"name": "=cmd()"}}).status_code, 400)
        self.assertEqual(self.api("patch", "api_import_row", body["id"], 2, body={"values": {"status": "APPROVED"}}).status_code, 400)
        self.assertEqual(self.api("patch", "api_import_row", body["id"], 2, body={"values": {"image_url": "http://x"}}).status_code, 400)
        self.assertEqual(self.api("patch", "api_import_row", body["id"], 2, body={}).status_code, 400)
        self.assertEqual(self.api("patch", "api_import_row", body["id"], 99, body={"values": {"name": "n"}}).status_code, 404)

    def test_detail_returns_rows_and_filters_by_status(self):
        body = self.preview([self.row(), self.row(sku="B", store_price=None)], all_or_nothing="false").json()
        detail = self.api("get", "api_import_detail", body["id"], status="incomplete").json()
        self.assertEqual([r["sku"] for r in detail["rows"]], ["B"])

    def test_other_users_cannot_read_or_edit_a_batch(self):
        body = self.preview([self.row()]).json()
        other = User.objects.create_user("other", "other@example.com", "x" * 12, is_staff=True)
        self.client.force_login(other)
        self.assertIn(self.api("get", "api_import_detail", body["id"]).status_code, (403, 404))
        self.assertIn(self.api("patch", "api_import_row", body["id"], 2, body={"values": {"name": "n"}}).status_code, (403, 404))

    def test_retry_imports_only_the_remaining_rows_without_duplicates(self):
        body = self.preview([self.row(), self.row(sku="R2")], all_or_nothing="false").json()
        real, calls = Product.save, []

        def flaky(self_, *a, **k):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("boom")
            return real(self_, *a, **k)

        with mock.patch.object(Product, "save", flaky):
            first = self.commit(body["id"]).json()
        self.assertEqual((first["summary"]["created"], first["summary"]["failed"]), (1, 1))
        self.assertTrue(first["retryable"])
        retry = self.api("post", "api_import_retry", body["id"])
        self.assertEqual(retry.status_code, 200, retry.content)
        summary = retry.json()["summary"]
        self.assertEqual((summary["created"], summary["failed"], retry.json()["attempts"]), (2, 0, 2))
        self.assertEqual(Product.objects.count(), 2)
        self.assertEqual(self.api("post", "api_import_retry", body["id"]).status_code, 409)  # nothing left
        self.assertEqual(self.commit(body["id"]).status_code, 200)  # double submit stays idempotent
        self.assertEqual(Product.objects.count(), 2)

    def test_job_list_shows_filename_user_counts_and_status(self):
        self.preview([self.row()])
        data = self.api("get", "api_import_list").json()
        self.assertEqual(data["count"], 1)
        item = data["results"][0]
        self.assertEqual((item["source_name"], item["created_by"], item["counts"]["total"], item["status"]), ("products.xlsx", "root", 1, "PREVIEWED"))
        other = User.objects.create_user("other2", "o2@example.com", "x" * 12, is_staff=True)
        self.client.force_login(other)
        self.assertIn(self.api("get", "api_import_list").status_code, (403,))

    def test_columns_endpoint_documents_aliases(self):
        cols = {c["key"]: c for c in self.api("get", "api_import_columns").json()["columns"]}
        self.assertIn("title", cols["name"]["aliases"])
        self.assertTrue(cols["store_price"]["required"])

    def test_fix_a_left_out_row_after_a_partial_import_then_retry(self):
        body = self.preview([self.row(), self.row(sku="LATER", store_price="abc")], all_or_nothing="false").json()
        first = self.commit(body["id"]).json()
        self.assertEqual((first["summary"]["created"], first["summary"]["failed"], first["retryable"]), (1, 1, True))
        detail = self.api("get", "api_import_detail", body["id"]).json()
        self.assertEqual({r["sku"]: r["status"] for r in detail["rows"]}, {"RICE-1": "skip", "LATER": "invalid"})  # imported row is not a "duplicate"
        fixed = self.api("patch", "api_import_row", body["id"], 3, body={"values": {"store_price": "12.50"}})
        self.assertEqual(fixed.json()["row"]["status"], "valid")
        retried = self.api("post", "api_import_retry", body["id"]).json()
        self.assertEqual((retried["summary"]["created"], retried["summary"]["failed"]), (2, 0))
        self.assertEqual(str(Product.objects.get(sku="LATER").store_price), "12.50")
        self.assertFalse(retried["retryable"])
