"""Customer navigation uses supported password authentication routes."""

from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import RegistrationSource
from .services import create_customer_with_user


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.current = {**dict(attrs), 'text': ''}

    def handle_data(self, data):
        if self.current is not None:
            self.current['text'] += data

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            self.current['text'] = ' '.join(self.current['text'].split())
            self.links.append(self.current)
            self.current = None


class CustomerNavigationTests(TestCase):
    def page_links(self, route):
        response = self.client.get(reverse(route))
        self.assertEqual(response.status_code, 200)
        links = Links(response.content.decode()).links
        retired = reverse('customers:customer_otp_start')
        self.assertFalse(any(link.get('href', '').startswith(retired) for link in links))
        self.assertNotContains(response, 'mobile number &amp; OTP')
        return links

    def assert_link(self, links, text, route, css_class=None):
        matching = [link for link in links if link['text'] == text and (
            css_class is None or css_class in link.get('class', '').split()
        )]
        self.assertTrue(matching, f'Missing {text!r} link with class {css_class!r}')
        self.assertTrue(all(link.get('href') == reverse(route) for link in matching))

    def test_public_desktop_navigation_uses_password_login_and_registration(self):
        links = self.page_links('catalog:public_home')
        self.assert_link(links, 'Login', 'customers:customer_portal_login', 'd-md-inline-flex')
        self.assert_link(links, 'Sign up', 'customers:customer_register', 'd-md-inline-flex')

    def test_public_mobile_navigation_uses_password_login_and_registration(self):
        links = self.page_links('catalog:public_home')
        self.assert_link(links, 'Login', 'customers:customer_portal_login', 'mobile-nav-link')
        self.assert_link(links, 'Sign up', 'customers:customer_register', 'mobile-nav-link')

    def test_product_listing_uses_supported_navigation(self):
        links = self.page_links('catalog:public_product_list')
        self.assert_link(links, 'Login', 'customers:customer_portal_login')
        self.assert_link(links, 'Sign up', 'customers:customer_register')

    def test_login_page_offers_registration_without_retired_otp_prompt(self):
        links = self.page_links('customers:customer_portal_login')
        self.assert_link(links, 'Login', 'customers:customer_portal_login')
        self.assert_link(links, 'Sign up', 'customers:customer_register')
        self.assert_link(links, 'Create an account', 'customers:customer_register')

    def test_registration_page_offers_password_login_without_retired_otp_prompt(self):
        links = self.page_links('customers:customer_register')
        self.assert_link(links, 'Login', 'customers:customer_portal_login')
        self.assert_link(links, 'Sign up', 'customers:customer_register')
        self.assert_link(links, 'Sign in', 'customers:customer_portal_login')

    def test_authenticated_navigation_keeps_account_links_and_post_logout(self):
        _, user = create_customer_with_user(user_data={
            'username': 'navigation-customer', 'email': 'navigation@example.com',
            'first_name': 'Navigation', 'last_name': 'Customer',
            'phone_number': '9000000092', 'password': 'Local-password-123!',
        }, registration_source=RegistrationSource.WEBSITE)
        self.client.force_login(user)
        links = self.page_links('catalog:public_home')
        self.assert_link(links, 'Account', 'customers:customer_portal_dashboard')
        self.assertFalse(any(link['text'] in {'Login', 'Sign up'} for link in links))
        response = self.client.get(reverse('customers:customer_portal_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'action="{reverse("customers:customer_portal_logout")}"')
        self.assertNotContains(response, reverse('customers:customer_otp_start'))

    def test_retired_routes_still_return_410_for_get_and_valid_csrf_post(self):
        client = Client(enforce_csrf_checks=True)
        client.get(reverse('customers:customer_portal_login'))
        token = client.cookies['csrftoken'].value
        before = get_user_model().objects.count()
        for name in ('start', 'verify', 'resend', 'profile'):
            url = reverse('customers:customer_otp_' + name)
            for response in (client.get(url), client.post(url, {'otp_code': '1234'}, HTTP_X_CSRFTOKEN=token)):
                self.assertEqual(response.status_code, 410)
                self.assertIn('no-store', response['Cache-Control'])
                self.assertNotIn(b'1234', response.content)
        self.assertNotIn('_auth_user_id', client.session)
        self.assertEqual(get_user_model().objects.count(), before)
