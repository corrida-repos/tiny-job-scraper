"""Current public Eightfold search inventory and detail integrity."""
import json
import unittest
from pathlib import Path

from pm_scraper.fetchers import Fetcher
from pm_scraper.filtering import Screener
from pm_scraper.http import FetchError

CFG = json.loads((Path(__file__).resolve().parents[1] / 'config/criteria.json').read_text())
BASE = 'https://example.org'
SOURCE = {'adapter': 'eightfold_pcsx', 'base': BASE, 'domain': 'example.org', 'max_pages': 200}
DESCRIPTION = 'Coordinate delivery, stakeholder expectations and risk registers across multiple complex projects.'


def search(start):
    return BASE + f'/api/pcsx/search?domain=example.org&query=&location=&start={start}'


def page(rows, count):
    return {'status': 200, 'error': {'message': '', 'body': ''}, 'data': {'positions': rows, 'count': count}, 'metadata': None}


def row(sid, title='Engineer'):
    return {'id': sid, 'name': title}


def job_url(sid):
    return BASE + f'/careers/job/{sid}?domain=example.org'


def detail_url(sid):
    return BASE + f'/api/pcsx/position_details?position_id={sid}&domain=example.org&hl=en'


def schema(sid, title='Project Manager'):
    return '<script type="application/ld+json">' + json.dumps({
        '@type': 'JobPosting', 'url': job_url(sid), 'title': title,
        'description': DESCRIPTION, 'datePosted': '2026-10-20',
    }) + '</script>'


class Pages:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def text(self, url, **kwargs):
        self.calls.append(url)
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        return value

    def json(self, url, **kwargs):
        return self.text(url, **kwargs)


class PcsxTests(unittest.TestCase):
    def fetch(self, responses, max_pages=None, max_details=250):
        http = Pages(responses)
        result = Fetcher(http, Screener(CFG), max_pages=max_pages, max_details=max_details).fetch(
            {'id': 'example', 'name': 'Example', 'source': SOURCE})
        return result, http

    def test_paginates_using_actual_row_count_and_matches_job_identity(self):
        result, http = self.fetch({
            search(0): page([row(1), row(2, 'Project Manager')], 3),
            search(2): page([row(3)], 3), job_url(2): schema(2),
        })
        self.assertTrue(result.complete)
        self.assertEqual(result.discovered, 3)
        self.assertIn(search(2), http.calls)
        self.assertEqual(result.jobs[0].source_id, '2')
        self.assertEqual(result.jobs[0].date_kind, 'original_posted')
        self.assertTrue(result.jobs[0].detail_ok)

    def test_empty_inventory_requires_explicit_zero(self):
        result, _ = self.fetch({search(0): page([], 0)})
        self.assertTrue(result.complete)
        for count in [None, -1, True, '0', 4]:
            with self.subTest(count=count):
                result, _ = self.fetch({search(0): page([], count)})
                self.assertFalse(result.complete)

    def test_repeated_page_cannot_complete(self):
        result, _ = self.fetch({search(0): page([row(1)], 3), search(1): page([row(1)], 3)})
        self.assertFalse(result.complete)
        self.assertEqual(result.status, 'pagination_error')

    def test_duplicates_and_total_changes_remain_partial(self):
        for second in [page([row(1)], 2), page([row(2)], 2)]:
            with self.subTest(second=second):
                result, _ = self.fetch({search(0): page([row(1)], 3), search(1): second})
                self.assertFalse(result.complete)

    def test_explicit_page_limit_overrides_company_default(self):
        result, http = self.fetch({search(0): page([row(1)], 2)}, max_pages=1)
        self.assertFalse(result.complete)
        self.assertEqual(http.calls, [search(0)])

    def test_source_default_allows_more_than_sixty_pages(self):
        responses = {search(i): page([row(i + 1)], 61) for i in range(61)}
        result, _ = self.fetch(responses)
        self.assertTrue(result.complete)
        self.assertEqual(result.discovered, 61)

    def test_cap_and_detail_failures_remain_visible(self):
        responses = {search(0): page([row(1, 'Project Manager')], 1),
                     job_url(1): FetchError('HTTP 403', 'blocked')}
        result, _ = self.fetch(responses)
        self.assertFalse(result.complete)
        self.assertIn('403', result.jobs[0].metadata['detail_error'])
        result, http = self.fetch(responses, max_details=0)
        self.assertFalse(result.complete)
        self.assertNotIn(job_url(1), http.calls)

    def test_schema_identity_ambiguity_and_missing_description_are_rejected(self):
        for body in [schema(999), schema(1) + schema(1), schema(1).replace(DESCRIPTION, 'Short')]:
            with self.subTest(body=body):
                result, _ = self.fetch({search(0): page([row(1, 'Project Manager')], 1), job_url(1): body})
                self.assertFalse(result.complete)
                self.assertFalse(result.jobs[0].detail_ok)

    def test_public_detail_fallback_does_not_promote_posted_ts_to_original_date(self):
        data = {'id': 1, 'name': 'Project Manager', 'jobDescription': DESCRIPTION,
                'standardizedLocations': ['Porto, PT'], 'workLocationOption': 'hybrid',
                'postedTs': 1792512000}
        result, _ = self.fetch({search(0): page([row(1, 'Project Manager')], 1),
                               job_url(1): '<html>Application shell</html>',
                               detail_url(1): {'status': 200, 'error': {'message': '', 'body': ''}, 'data': data, 'metadata': None}})
        self.assertTrue(result.complete)
        self.assertTrue(result.jobs[0].detail_ok)
        self.assertEqual(result.jobs[0].location, 'Porto, PT')
        self.assertIsNone(result.jobs[0].posted_at)
        self.assertEqual(result.jobs[0].date_kind, 'unknown')
        self.assertIn(detail_url(1), result.jobs[0].evidence)

    def test_detail_fallback_rejects_wrong_id_and_disappearing_jobs(self):
        for response in [FetchError('HTTP 404', 'not_found'),
                         {'status': 200, 'error': {'message': '', 'body': ''}, 'data': {'id': 2, 'name': 'Project Manager'}, 'metadata': None}]:
            result, _ = self.fetch({search(0): page([row(1, 'Project Manager')], 1),
                                   job_url(1): '<html>Shell</html>', detail_url(1): response})
            self.assertFalse(result.complete)

    def test_unsuccessful_and_fallback_envelopes_are_not_inventory(self):
        for update in [{'status': 404}, {'error': {'message': 'Unavailable'}},
                       {'metadata': {'isFallback': True}}, {'data': []}]:
            result, _ = self.fetch({search(0): page([], 0) | update})
            self.assertFalse(result.complete)

    def test_search_failure_does_not_claim_empty_inventory(self):
        result, http = self.fetch({search(0): FetchError('HTTP 403', 'blocked')})
        self.assertFalse(result.complete)
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(http.calls, [search(0)])
