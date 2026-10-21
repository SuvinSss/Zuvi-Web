"""Locust scenarios: public catalogue browsing + authenticated management API.

    locust -f loadtests/locustfile.py --headless -u 30 -r 5 -t 60s --host http://127.0.0.1:8001 --csv loadtests/results/run

Requires a throwaway database seeded by scripts/load_seed.py (user load_admin).
Raise API_THROTTLE_LOGIN / API_THROTTLE_USER on the *test server only* so throttling does not
mask server capacity (see docs/performance-testing.md).
"""
import random

from locust import HttpUser, between, task

QUERIES = ["organic", "fresh", "Product 0042", "load", "zzz-no-match"]


class Shopper(HttpUser):
    weight = 3
    wait_time = between(0.5, 2)

    @task(5)
    def list_page(self):
        self.client.get(f"/products/?page={random.randint(1, 20)}", name="/products/?page=N")

    @task(3)
    def search(self):
        self.client.get("/products/", params={"q": random.choice(QUERIES)}, name="/products/?q=")

    @task(1)
    def home(self):
        self.client.get("/", name="/")


class Manager(HttpUser):
    weight = 1
    wait_time = between(0.5, 2)

    def on_start(self):
        r = self.client.get("/api/v1/auth/session/", name="api session")
        token = r.json().get("csrf_token", "")
        self.client.post("/api/v1/auth/login/", json={"username": "load_admin", "password": "Load-pass-12345!"},
                         headers={"X-CSRFToken": token}, name="api login")

    @task(5)
    def list_products(self):
        self.client.get(f"/api/v1/products/?page={random.randint(1, 100)}&page_size=20", name="api products?page=N")

    @task(3)
    def search(self):
        self.client.get("/api/v1/products/", params={"q": random.choice(QUERIES)}, name="api products?q=")

    @task(2)
    def filter(self):
        self.client.get("/api/v1/products/", params={"status": "APPROVED", "ordering": "-created_at"}, name="api products?status=")

    @task(2)
    def detail(self):
        r = self.client.get("/api/v1/products/?page_size=5", name="api products?page_size=5")
        ids = [p["id"] for p in r.json().get("results", [])] if r.ok else []
        if ids:
            self.client.get(f"/api/v1/products/{random.choice(ids)}/", name="api product detail")

    @task(1)
    def meta(self):
        self.client.get("/api/v1/products/meta/", name="api meta")
