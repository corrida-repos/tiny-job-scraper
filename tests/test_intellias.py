"""Intellias AJAX listing: duplicate cards versus a real shortfall."""
import json
import unittest
from pathlib import Path

from pm_scraper.fetchers import Fetcher
from pm_scraper.filtering import Screener

CFG = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/criteria.json').read_text())
COMPANY = next(c for c in json.loads((Path(__file__).resolve().parents[1] / 'config/companies.json').read_text())
               if c['id'] == 'intellias')


def card(slug):
    return f'<a href="https://career.intellias.com/vacancy/{slug}/"><h3 class="title">Data Engineer</h3></a>'


class Ajax:
    """Two cards per page, as the live board repeats a card on a later page."""
    def __init__(self, posts, total):
        self.posts, self.total = posts, total

    def json(self, url, form=None, **kwargs):
        page = form['page']
        return {'posts': self.posts[2 * page - 2:2 * page], 'total': self.total, 'end': 2 * page >= len(self.posts)}

    def text(self, url, **kwargs):
        raise AssertionError('No detail pages should be read for unwanted titles: ' + url)


class IntelliasTests(unittest.TestCase):
    def fetch(self, posts, total):
        return Fetcher(Ajax(posts, total), Screener(CFG)).fetch(COMPANY)

    def test_duplicate_card_is_not_a_coverage_gap(self):
        result = self.fetch([card('a-1'), card('b-2'), card('c-3'), card('b-2')], 4)
        self.assertTrue(result.complete, result.messages)
        self.assertEqual(result.discovered, 3)
        self.assertIn('more than once', ' '.join(result.messages))

    def test_real_shortfall_remains_partial(self):
        result = self.fetch([card('a-1'), card('b-2'), card('c-3')], 4)
        self.assertFalse(result.complete)
        self.assertEqual(result.status, 'partial')


if __name__ == '__main__':
    unittest.main()
