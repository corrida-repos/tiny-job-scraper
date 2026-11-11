"""A content-feed "Load more" button is not job pagination."""
import json
import unittest
from pathlib import Path

from pm_scraper.fetchers import Fetcher
from pm_scraper.filtering import Screener

CFG = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/criteria.json').read_text())
SOURCE = {'adapter': 'html', 'kind': 'radancy', 'listing_url': 'https://example.org/en/jobs-portugal',
          'job_pattern': '/en/job/[^?#]+'}
JOBS = '<a href="/en/job/porto/data-engineer/1/2">Data Engineer</a>'
FEED = ('<button class=" button-primary js-hub-load-more-button hub__load-more-button enabled" '
        'data-hub-id="data-content-feed-ef6c0f71bb">Load more</button>')
JOB_BUTTON = '<button class="jobs-more">Load more</button>'


class Page:
    def __init__(self, body):
        self.body = body

    def text(self, url, **kwargs):
        return self.body


class ContentFeedButton(unittest.TestCase):
    def fetch(self, extra):
        body = '<html><body>' + JOBS + extra + '</body></html>'
        return Fetcher(Page(body), Screener(CFG)).fetch({'id': 'tui', 'name': 'TUI', 'source': SOURCE})

    def test_content_feed_button_is_ignored(self):
        result = self.fetch(FEED)
        self.assertTrue(result.complete, result.messages)

    def test_job_load_more_button_still_flags_partial(self):
        result = self.fetch(JOB_BUTTON)
        self.assertFalse(result.complete)
        self.assertIn('Dynamic pagination control found', ' '.join(result.messages))


if __name__ == '__main__':
    unittest.main()
