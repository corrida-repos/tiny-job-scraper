"""Residence requirements in descriptions and public forms override remote labels."""
import copy
import unittest

from pm_scraper.daily import prepare_email
from pm_scraper.fetchers import Fetcher
from pm_scraper.filtering import Screener
from pm_scraper.http import FetchError
from test_screening import BASE, CFG, NOW, job

QUESTION = 'Do you live local to Lisbon? This candidate must reside in Lisbon.'
COMPANY = {'id': 'salsify', 'name': 'Salsify', 'source': {'adapter': 'greenhouse', 'board': 'salsify'}}
ENDPOINT = 'https://boards-api.greenhouse.io/v1/boards/salsify/jobs/8516548002?questions=true'
POSTING = {'id': 8516548002, 'title': 'Senior GTM Strategy & Ops Program Manager',
           'absolute_url': 'https://www.salsify.com/careers/current-listings?gh_jid=8516548002',
           'location': {'name': 'Remote - Portugal'}, 'content': BASE,
           'first_published': '2026-10-18T12:00:00Z'}


class PublicBoard:
    def __init__(self, detail):
        self.detail = detail
        self.calls = []

    def json(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith('/jobs?content=true'):
            return {'jobs': [copy.deepcopy(POSTING)], 'meta': {'total': 1}}
        if url != ENDPOINT:
            raise AssertionError('Unexpected endpoint: ' + url)
        if isinstance(self.detail, Exception):
            raise self.detail
        return copy.deepcopy(self.detail)


class ResidenceTests(unittest.TestCase):
    def setUp(self):
        self.screener = Screener(CFG)
        self.payload = {'started_at': NOW.isoformat(), 'sources': [],
                        'coverage': {'sources': 1, 'complete': 1, 'attention': 0}}

    def assess_text(self, text):
        return self.screener.assess(job(description=BASE + ' ' + text), NOW)

    def test_explicit_residence_or_relocation_outside_north_is_rejected(self):
        for text in [QUESTION, 'You must live in Lisbon.', 'Candidates must be based in Madrid.',
                     'Applicants are required to be located in Coimbra.',
                     'You need to relocate to London.', 'Residency in Faro is mandatory.',
                     'This position requires you to live in Lisbon.',
                     'You must already be living in Lisbon.',
                     'You must reside in Lisbon, but relocation is not required.',
                     'O candidato deve residir em Lisboa.', 'Residência obrigatória em Setúbal.',
                     'Residência em Lisboa é obrigatória.', 'You must live within commuting distance of Lisbon.']:
            with self.subTest(text=text):
                assessment = self.assess_text(text)
                self.assertEqual(assessment.checks['residence']['status'], 'fail')
                self.assertEqual(assessment.status, 'rejected')

    def test_permitted_residence_and_optional_relocation_do_not_exclude(self):
        for text in ['You must reside in Porto.', 'You must live in Braga.',
                     'You must be based in Santo Tirso.', 'You must reside in Vila Nova de Gaia.',
                     'You must live in the Porto area.', 'You must reside in Portugal to work remotely.',
                     'Candidates must be based in Lisbon or Porto.', 'Residência em Lisboa ou Braga é obrigatória.',
                     'Residence in Lisbon is preferred.', 'You are not required to live in Lisbon.',
                     'Relocation to Lisbon is not required.', 'Our head office is in Lisbon.',
                     'Do you live in Lisbon?', 'Remote from anywhere in Portugal.']:
            with self.subTest(text=text):
                self.assertEqual(self.assess_text(text).checks['residence']['status'], 'pass')

    def test_residence_allowlist_is_configurable_and_not_an_attendance_setting(self):
        restricted = Screener({**CFG, 'allowed_residence_locations': ['Santo Tirso']})
        self.assertEqual(restricted.assess(job(description=BASE + ' You must reside in Braga.'), NOW).checks['residence']['status'], 'fail')
        self.assertEqual(restricted.assess(job(description=BASE + ' You must reside in Santo Tirso.'), NOW).checks['residence']['status'], 'pass')

    def test_exact_salsify_question_is_retrieved_and_excluded_from_email(self):
        http = PublicBoard({'id': POSTING['id'], 'questions': [{'label': QUESTION, 'description': None, 'required': True}]})
        result = Fetcher(http, self.screener).fetch(COMPANY)
        self.assertTrue(result.complete)
        candidate = result.jobs[0]
        self.assertIn(ENDPOINT, http.calls)
        self.assertIn(ENDPOINT, candidate.evidence)
        self.assertEqual(candidate.metadata['application_questions'][0]['label'], QUESTION)
        assessment = self.screener.assess(candidate, NOW)
        self.assertEqual(assessment.checks['freshness']['status'], 'pass')
        self.assertEqual(assessment.checks['residence']['status'], 'fail')
        self.assertEqual(prepare_email([(candidate, assessment)], self.payload)['job_keys'], [])

    def test_question_description_is_screened_and_generic_questions_not_assumed_disqualifying(self):
        for label, description, expected in [('Residence', '<p>You must reside in Lisbon.</p>', 'fail'),
                                              ('Do you live in Lisbon?', None, 'pass')]:
            with self.subTest(label=label):
                http = PublicBoard({'id': POSTING['id'], 'questions': [{'label': label, 'description': description, 'required': True}]})
                candidate = Fetcher(http, self.screener).fetch(COMPANY).jobs[0]
                self.assertEqual(self.screener.assess(candidate, NOW).checks['residence']['status'], expected)

    def test_failed_or_malformed_question_retrieval_never_reports_fresh_candidate(self):
        for detail in [FetchError('HTTP 403', 'blocked'), {'id': POSTING['id']},
                       {'id': 0, 'questions': []}, {'id': POSTING['id'], 'questions': 'changed'},
                       {'id': POSTING['id'], 'questions': [{'label': QUESTION, 'required': 'true'}]}]:
            with self.subTest(detail=detail):
                result = Fetcher(PublicBoard(detail), self.screener).fetch(COMPANY)
                self.assertFalse(result.complete)
                candidate = result.jobs[0]
                assessment = self.screener.assess(candidate, NOW)
                self.assertFalse(candidate.metadata['application_requirements_checked'])
                self.assertEqual(assessment.checks['application_requirements']['status'], 'unknown')
                self.assertEqual(prepare_email([(candidate, assessment)], self.payload)['job_keys'], [])

    def test_detail_cap_withholds_unchecked_application_requirements(self):
        http = PublicBoard({'id': POSTING['id'], 'questions': []})
        result = Fetcher(http, self.screener, max_details=0).fetch(COMPANY)
        self.assertFalse(result.complete)
        self.assertNotIn(ENDPOINT, http.calls)
        candidate = result.jobs[0]
        self.assertEqual(prepare_email([(candidate, self.screener.assess(candidate, NOW))], self.payload)['job_keys'], [])

    def test_no_custom_questions_is_checked_and_can_report(self):
        candidate = Fetcher(PublicBoard({'id': POSTING['id'], 'questions': []}), self.screener).fetch(COMPANY).jobs[0]
        self.assertTrue(candidate.metadata['application_requirements_checked'])
        assessment = self.screener.assess(candidate, NOW)
        self.assertEqual(assessment.status, 'eligible')
        self.assertEqual(prepare_email([(candidate, assessment)], self.payload)['job_keys'], [candidate.key])
