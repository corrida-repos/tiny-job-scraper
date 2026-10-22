"""Report readability and self-contained email logo delivery."""
import json
from pathlib import Path
import re
import struct
import unittest
from unittest.mock import patch

from lxml import html

from pm_scraper.actions_runner import Gmail
from pm_scraper.branding import company_heading, logos, render_email_html, URL_BASE
from pm_scraper.daily import clean, display_title, fragments, prepare_email
from pm_scraper.filtering import Screener
from test_screening import CFG, NOW, job

ROOT = Path(__file__).resolve().parents[1]


class PresentationTests(unittest.TestCase):
    def test_official_logo_inventory_covers_all_active_companies_with_valid_pngs(self):
        companies = json.loads((ROOT/'config/companies.json').read_text())
        self.assertEqual(set(logos()), {c['id'] for c in companies})
        for company, path in logos().items():
            with self.subTest(company=company):
                data = path.read_bytes()
                self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('>II', data[16:24]), (256, 52) if company == 'intellias' else (64, 64))

    def test_logo_is_next_to_company_and_embedded_only_once_when_repeated(self):
        heading = company_heading('bosch', 'Bosch')
        rendered, images = render_email_html(heading+'\n\n'+heading)
        document = html.fromstring(rendered)
        self.assertEqual(len(document.xpath('//h2/img')), 2)
        self.assertEqual(document.xpath('//h2/img/@src'), ['cid:tiny-logo-bosch']*2)
        self.assertEqual(document.xpath('//h2/img/@width'), ['32']*2)
        self.assertEqual([cid for cid, data in images], ['tiny-logo-bosch'])
        self.assertNotIn(URL_BASE, rendered)
        self.assertEqual(company_heading('unconfigured', 'Other'), '## Other')

    def test_html_preview_uses_logo_urls_without_email_attachments(self):
        rendered, images = render_email_html(company_heading('bosch', 'Bosch'), embed=False)
        self.assertIn(URL_BASE+'bosch.png', rendered)
        self.assertEqual(images, [])

    def test_email_contains_inline_png_related_to_html_without_network_image_fetching(self):
        draft = {'subject': 'Fixture', 'body_markdown': company_heading('bosch', 'Bosch')}
        with patch('pm_scraper.actions_runner.smtplib.SMTP_SSL') as smtp:
            smtp.return_value.__enter__.return_value.send_message.return_value = {}
            Gmail('sender@example.org', 'fixture').send('recipient@example.org', draft, '<fixture@example.org>')
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        images = [part for part in message.walk() if part.get_content_type() == 'image/png']
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]['Content-ID'], '<tiny-logo-bosch>')
        self.assertEqual(images[0].get_content_disposition(), 'inline')
        self.assertEqual(images[0].get_payload(decode=True), logos()['bosch'].read_bytes())
        html_part = next(part for part in message.walk() if part.get_content_type() == 'text/html')
        self.assertIn('src="cid:tiny-logo-bosch"', html_part.get_content())

    def test_empty_delimiters_are_removed_without_damaging_salary_numbers(self):
        self.assertEqual(clean(' Porto; ; ; Portugal, , Remote '), 'Porto; Portugal, Remote')
        self.assertEqual(fragments(['', '; ;', None, 'Porto', ', ,', '€40,000–€60,000']), 'Porto; €40,000–€60,000')
        self.assertEqual(clean('€40,000–€60,000'), '€40,000–€60,000')

    def test_gender_markers_are_removed_only_from_display_title(self):
        for marker in ['(f/m/div.)', '(m/f/d)', '(m/w/d)', '(all genders)', '(F / M / DIV.)']:
            with self.subTest(marker=marker):
                title = 'Project Manager '+marker
                candidate = job(title=title)
                assessed = Screener(CFG).assess(candidate, NOW)
                payload = {'started_at': NOW.isoformat(), 'sources': [], 'coverage': {'sources': 1, 'complete': 1, 'attention': 0}}
                draft = prepare_email([(candidate, assessed)], payload)
                self.assertIn('### **Project Manager**\n', draft['body_markdown'])
                self.assertEqual(candidate.title, title)
        self.assertEqual(display_title('Project Manager (AI/ML)'), 'Project Manager (AI/ML)')

    def test_company_and_position_headings_have_no_numbering_and_no_empty_fragments(self):
        candidate = job(title='Project Manager (f/m/div.)')
        assessed = Screener(CFG).assess(candidate, NOW)
        assessed.checks['travel'] = {'status': 'unknown', 'evidence': '; ;'}
        assessed.checks['attendance']['evidence'] = ', ,'
        payload = {'started_at': NOW.isoformat(), 'sources': [], 'coverage': {'sources': 1, 'complete': 1, 'attention': 0}}
        text = prepare_email([(candidate, assessed)], payload)['body_markdown']
        self.assertNotRegex(text, r'(?m)^#{2,3}\s+\d')
        self.assertNotRegex(text, r'[,;]\s*[,;]')
        self.assertIn('### **Project Manager**', text)
