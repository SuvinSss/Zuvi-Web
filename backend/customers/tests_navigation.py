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

    def assert_link(self, links, text, route, css_class=None):
        matching = [link for link in links if link['text'] == text and (
            css_class is None or css_class in link.get('class', '').split()
        )]
        self.assertTrue(matching, f'Missing {text!r} link with class {css_class!r}')
        self.assertTrue(all(link.get('href') == reverse(route) for link in matching))







