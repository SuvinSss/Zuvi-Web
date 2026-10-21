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
