"""Secondary discovery must preserve identity, freshness and coverage uncertainty."""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from pm_scraper.fetchers import Fetcher
from pm_scraper.filtering import Screener
from pm_scraper.http import FetchError

FEED = 'https://weworkremotely.com/remote-jobs.rss'
URL = 'https://weworkremotely.com/remote-jobs/float-project-manager'
CFG = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/criteria.json').read_text())
DESCRIPTION = '<p><strong>URL:</strong> <a href="https://float.com">float.com</a></p><p>Manage project delivery, stakeholder expectations and risk registers across complex projects.</p>'
SOURCE = {'adapter': 'html', 'listing_url': 'https://float.com/careers', 'job_pattern': '/jobs/',
          'wwr_fallback': {'employer_names': ['Float'], 'employer_hosts': ['float.com', 'www.float.com']}}


def item(title='Float: Project Manager', description=DESCRIPTION, url=URL):
    return ('<item><title>' + escape(title) + '</title><link>' + escape(url) + '</link>'
            '<description>' + escape(description) + '</description><region>Anywhere in the World</region>'
            '<pubDate>Wed, 21 Oct 2026 08:00:00 +0000</pubDate></item>')


def feed(items='', channel=FEED):
    return '<rss><channel><link>' + channel + '</link>' + items + '</channel></rss>'


class Pages:
    def __init__(self, body, primary=None):
        self.body, self.primary, self.calls = body, primary, []

    def text(self, url, **kwargs):
        self.calls.append(url)
        if url == SOURCE['listing_url']:
            if self.primary is not None:
                return self.primary
            raise FetchError('HTTP 403: employer inventory unavailable', 'blocked')
        if url != FEED:
            raise AssertionError('Unexpected request: ' + url)
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class SupplementalFeedTests(unittest.TestCase):
    def fetch(self, body, primary=None):
        http = Pages(body, primary)
        result = Fetcher(http, Screener(CFG)).fetch({'id': 'float', 'name': 'Float', 'source': SOURCE})
        return result, http

    def test_matching_employer_is_recovered_but_stays_partial(self):
        result, http = self.fetch(feed(item()))
        self.assertEqual(result.status, 'partial')
        self.assertFalse(result.complete)
        self.assertEqual(len(result.jobs), 1)
        self.assertTrue(result.jobs[0].detail_ok)
        self.assertIn('403', result.messages[0])
        self.assertEqual(http.calls, [SOURCE['listing_url'], FEED])

    def test_recent_syndication_does_not_pass_original_freshness(self):
        result, _ = self.fetch(feed(item()))
        job = result.jobs[0]
        self.assertIsNone(job.posted_at)
        self.assertTrue(job.metadata['original_date_unproven'])
        assessment = Screener(CFG).assess(job, now=datetime(2026, 10, 21, 9, tzinfo=timezone.utc))
        self.assertNotEqual(assessment.checks['freshness']['status'], 'pass')

    def test_name_and_explicit_official_url_must_both_match(self):
        for listing in [item(title='Float Financial: Project Manager'),
                        item(description=DESCRIPTION.replace('https://float.com', 'https://other.example')),
                        item(description=DESCRIPTION.replace('https://float.com', 'https://float.com.other.example')),
                        item(description='<p>Mentions <a href="https://float.com">Float</a></p>'),
                        item(description=DESCRIPTION.replace('https://float.com', 'https://[broken')),
                        item(description=DESCRIPTION + '<p><strong>URL:</strong><a href="https://other.example">Other</a></p>')]:
            with self.subTest(listing=listing):
                result, _ = self.fetch(feed(listing))
                self.assertFalse(result.complete)
                self.assertEqual(result.jobs, [])

    def test_external_or_non_job_urls_are_not_followed(self):
        for url in ['https://other.example/remote-jobs/float-project-manager',
                    'https://weworkremotely.com/company/float',
                    'http://weworkremotely.com/remote-jobs/float-project-manager']:
            result, http = self.fetch(feed(item(url=url)))
            self.assertEqual(result.jobs, [])
            self.assertEqual(http.calls, [SOURCE['listing_url'], FEED])

    def test_duplicate_feed_items_are_counted_once(self):
        result, _ = self.fetch(feed(item() + item()))
        self.assertEqual(result.discovered, 1)
        self.assertEqual(len(result.jobs), 1)

    def test_empty_secondary_feed_does_not_mean_empty_employer_inventory(self):
        result, _ = self.fetch(feed())
        self.assertFalse(result.complete)
        self.assertEqual(result.status, 'partial')
        self.assertIn('0 employer listings', result.messages[-1])

    def test_broken_feed_preserves_primary_failure(self):
        for body in ['<html>Page</html>', '<rss>', feed(item(), channel='https://other.example'),
                     FetchError('robots.txt disallows feed', 'robots_denied')]:
            result, _ = self.fetch(body)
            self.assertEqual(result.status, 'blocked')
            self.assertFalse(result.complete)
            self.assertEqual(result.jobs, [])
            self.assertIn('Secondary WWR feed unavailable', result.messages[-1])

    def test_successful_primary_does_not_request_secondary_feed(self):
        result, http = self.fetch(feed(item()), '<a href="/jobs/1">Software Engineer</a>')
        self.assertTrue(result.complete)
        self.assertNotIn(FEED, http.calls)

    def test_unwanted_roles_are_counted_without_becoming_candidates(self):
        result, _ = self.fetch(feed(item(title='Float: Software Engineer')))
        self.assertEqual(result.discovered, 1)
        self.assertEqual(result.jobs, [])
        self.assertFalse(result.complete)

    def test_noesis_configuration_requires_its_official_domain(self):
        companies = json.loads((Path(__file__).resolve().parents[1] / 'config/companies.json').read_text())
        company = next(c for c in companies if c['id'] == 'noesis')
        class NoesisPages(Pages):
            def text(self, url, **kwargs):
                if url == company['source']['listing_url']:
                    raise FetchError('HTTP 403: Noesis inventory unavailable', 'blocked')
                return super().text(url, **kwargs)
        for host, count in [('noesis.pt', 1), ('www.noesis.pt', 1), ('noesis.com', 0),
                            ('noesis.pt.other.example', 0)]:
            with self.subTest(host=host):
                body = feed(item(title='Noesis: Project Manager',
                                 description=DESCRIPTION.replace('float.com', host),
                                 url='https://weworkremotely.com/remote-jobs/noesis-project-manager'))
                result = Fetcher(NoesisPages(body), Screener(CFG)).fetch(company)
                self.assertEqual(len(result.jobs), count)
                self.assertFalse(result.complete)
                self.assertIn('403', result.messages[0])
