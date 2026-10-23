from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from catalog.models import ProductStatus, Tag
from catalog.tests_public import PublicCatalogueTestMixin


class SearchSuggestionsTests(PublicCatalogueTestMixin, TestCase):
    def setUp(self):
        self.store = self.create_store()
        self.bread = self.create_public_product(store=self.store, name="Whole wheat bread")
        self.tomato = self.create_public_product(store=self.store, name="Fresh tomatoes")
        self.url = reverse("catalog:public_search_suggestions")

    def suggestions(self, query):
        response = self.client.get(self.url, {"q": query})
        self.assertEqual(response.status_code, 200)
        return response.json()["results"]

    def test_typo_matches_both_dropdown_and_results(self):
        for query, product in [("bred", self.bread), ("tomatoe", self.tomato), ("tomtaoes", self.tomato)]:
            with self.subTest(query=query):
                self.assertIn(product.name, [r["label"] for r in self.suggestions(query)])
                response = self.client.get(reverse("catalog:public_product_list"), {"q": query})
                self.assertContains(response, product.name)
                if query not in product.name.lower():
                    self.assertContains(response, "Includes close spelling matches")

    def test_exact_match_ranks_before_typo(self):
        exact = self.create_public_product(store=self.store, name="Bred")
        self.assertEqual(self.suggestions("bred")[0]["label"], exact.name)

    def test_hidden_products_never_leak_into_suggestions(self):
        self.create_public_product(store=self.store, name="Bread pending secret", status=ProductStatus.PENDING)
        self.create_public_product(store=self.store, name="Bread inactive secret", is_active=False)
        self.create_public_product(store=self.store, name="Bread empty secret", stock=0)
        labels = [r["label"] for r in self.suggestions("bread")]
        self.assertEqual(labels, [self.bread.name])
        self.store.is_active = False
        self.store.save(update_fields=["is_active"])
        self.assertEqual(self.suggestions("bread"), [])

    def test_no_sensitive_fields(self):
        result = self.suggestions("bread")[0]
        self.assertEqual(set(result), {"label", "detail", "kind", "url"})
        self.assertNotIn(self.store.name, str(result))

    def test_empty_short_nonsense_and_long_queries(self):
        for query in ["", "zzzzqqqq", "x" * 200]:
            self.assertEqual(self.suggestions(query), [])
        self.assertEqual(self.client.post(self.url, {"q": "bread"}).status_code, 405)

    def test_multiple_tags_do_not_duplicate_results(self):
        self.bread.tags.add(Tag.objects.create(name="Bread specials"), Tag.objects.create(name="Daily"))
        self.assertEqual([r["label"] for r in self.suggestions("bread")], [self.bread.name])

    def test_explicit_price_sort_and_filter_remain_effective(self):
        response = self.client.get(reverse("catalog:public_product_list"), {"q": "bred", "max_price": "1", "sort": "price"})
        self.assertEqual(response.context["result_count"], 0)

    def test_blank_search_with_invalid_filter_does_not_crash(self):
        response = self.client.get(
            reverse("catalog:public_product_list"),
            {"q": "   ", "min_price": "invalid"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("min_price", response.context["filter_form"].errors)

    def test_suggestions_start_with_first_character(self):
        self.assertIn(self.bread.name, [r["label"] for r in self.suggestions("b")])


class ManglishSearchTests(PublicCatalogueTestMixin, TestCase):
    def setUp(self):
        self.store = self.create_store()
        self.parippu = self.create_public_product(store=self.store, name="Parippu 1kg")
        self.oil = self.create_public_product(store=self.store, name="Coconut Oil 1L")
        self.rice = self.create_public_product(store=self.store, name="Kerala Rice 5kg")
        self.marie = self.create_public_product(store=self.store, name="Marie Biscuit")

    def results(self, query):
        response = self.client.get(reverse("catalog:public_product_list"), {"q": query})
        return {p["name"] if isinstance(p, dict) else p.name for p in response.context["products"]}, response

    def test_english_finds_manglish_and_back(self):
        for query, product in [
            ("dal", self.parippu),
            ("velichenna", self.oil),
            ("Velichenna 1 litre", self.oil),
            ("അരി", self.rice),
            ("ari", self.rice),
        ]:
            with self.subTest(query=query):
                names, response = self.results(query)
                self.assertIn(product.name, names)
                self.assertNotContains(response, "Includes close spelling matches")

    def test_short_synonym_needs_whole_word(self):
        names, _ = self.results("അരി")
        self.assertNotIn(self.marie.name, names)

    def test_search_keywords_and_typos(self):
        dal = self.create_public_product(store=self.store, name="Toor Dal Premium", search_keywords="thuvara parippu")
        self.assertIn(dal.name, self.results("thuvara")[0])
        self.assertIn(dal.name, self.results("thuvra parippu")[0])

    def test_synonyms_never_show_hidden_products(self):
        self.create_public_product(store=self.store, name="Hidden Parippu", status=ProductStatus.PENDING)
        self.create_public_product(store=self.store, name="Empty Parippu", stock=0)
        names, _ = self.results("dal")
        self.assertEqual(names, {self.parippu.name})

    def test_keywords_not_exposed_publicly(self):
        self.oil.search_keywords = "secretword-velichenna"
        self.oil.save(update_fields=["search_keywords"])
        response = self.client.get(reverse("catalog:public_search_suggestions"), {"q": "velichenna"})
        self.assertNotIn("secretword", response.content.decode())
        _, page = self.results("velichenna")
        self.assertNotContains(page, "secretword")


class SearchKeywordCommandTests(PublicCatalogueTestMixin, TestCase):
    def setUp(self):
        self.store = self.create_store()
        self.rice = self.create_public_product(store=self.store, name="Matta Rice 5kg")
        self.lamp = self.create_public_product(store=self.store, name="Desk Lamp")

    def run_command(self, *args):
        out = StringIO()
        call_command(*args, stdout=out)
        return out.getvalue()

    def test_fill_dry_run_writes_nothing_then_fills(self):
        output = self.run_command("fill_search_keywords", "--store", self.store.name, "--dry-run")
        self.assertIn("kuthari", output)
        self.assertIn(self.lamp.name, output.split("No dictionary match")[1])
        self.rice.refresh_from_db()
        self.assertEqual(self.rice.search_keywords, "")
        self.run_command("fill_search_keywords", "--store", self.store.name)
        self.rice.refresh_from_db()
        self.assertIn("kuthari", self.rice.search_keywords)

    def test_fill_keeps_manual_keywords(self):
        self.rice.search_keywords = "chuvanna ari"
        self.rice.save(update_fields=["search_keywords"])
        self.run_command("fill_search_keywords", "--store", self.store.name)
        self.rice.refresh_from_db()
        self.assertTrue(self.rice.search_keywords.startswith("chuvanna ari, "))

    def test_audit_reports_hidden_reasons(self):
        self.create_public_product(store=self.store, name="Pending Item", status=ProductStatus.PENDING)
        self.create_public_product(store=self.store, name="No Stock Item", stock=0)
        output = self.run_command("audit_store_search", "--store", self.store.name)
        self.assertIn("status is PENDING", output)
        self.assertIn("out of stock", output)
        self.assertIn("2 public, 2 hidden", output)
