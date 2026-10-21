"""Diagnostics must distinguish source gaps from failed/stale executions."""
import json
from io import StringIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pm_scraper.coverage_check import GAPS, annotation, check, selected_sources, summary, validate_health


def audit(source='noesis', complete=False):
    return {'company_id': source, 'company': source, 'complete': complete,
            'status': 'ok' if complete else 'partial', 'discovered': 0,
            'pages': 1, 'candidates': 0, 'messages': ['HTTP 403; secondary feed empty']}


class CoverageCheckTests(unittest.TestCase):
    def setUp(self):
        # Fixture diagnostics must not become live GitHub Actions annotations.
        stdout = patch('sys.stdout', new_callable=StringIO)
        stdout.start()
        self.addCleanup(stdout.stop)

    def test_selection_rejects_other_employers_and_shell_text(self):
        self.assertEqual(selected_sources('all-gaps'), GAPS)
        self.assertEqual(selected_sources('noesis'), ('noesis',))
        for selection in ('', 'infineon', 'noesis,float', '$(echo bad)'):
            with self.assertRaises(ValueError):
                selected_sources(selection)

    def test_incomplete_is_a_successful_diagnostic_only_with_valid_audit(self):
        self.assertEqual(validate_health([audit()], ('noesis',), 2), 0)
        self.assertEqual(validate_health([audit(complete=True)], ('noesis',), 0), 1)
        cases = [([], 2), ([audit('float')], 2), ([audit(), audit()], 2),
                 ([audit()], 1), ([audit()], 0), ([audit(complete=True)], 2),
                 ([dict(audit(), pages=-1)], 2), ([dict(audit(), complete='false')], 2),
                 ([dict(audit(), messages='bad')], 2), ([None], 2)]
        for health, code in cases:
            with self.subTest(health=health, code=code), self.assertRaises(ValueError):
                validate_health(health, ('noesis',), code)

    def test_disposable_state_and_only_audit_is_retained(self):
        paths = []
        def fake_run(args):
            state = Path(args[args.index('--state') + 1])
            out = Path(args[args.index('--output') + 1])
            paths.append(state.parent)
            self.assertFalse(state.exists())
            self.assertEqual(args[args.index('--only') + 1], 'noesis')
            self.assertEqual(args[args.index('--max-post-age-days') + 1], '2')
            state.write_text('disposable state')
            out.mkdir()
            (out / 'email.json').write_text('private draft')
            (out / 'source-health.json').write_text(json.dumps([audit()]))
            return 2
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('pm_scraper.coverage_check.cli.main', side_effect=fake_run):
                self.assertEqual(check('noesis', root / 'audit', root / 'summary'), 0)
            self.assertEqual({p.name for p in (root / 'audit').iterdir()},
                             {'source-health.json', 'summary.md'})
            self.assertIn('0/1 source scopes complete', (root / 'summary').read_text())
            self.assertFalse(paths[0].exists())

    def test_execution_failure_missing_or_invalid_audit_fails(self):
        for body, code in [(None, 2), ('not json', 2), (json.dumps([audit()]), 1), ('[]', 2)]:
            def fake_run(args):
                out = Path(args[args.index('--output') + 1])
                out.mkdir()
                if body is not None:
                    (out / 'source-health.json').write_text(body)
                return code
            with self.subTest(body=body, code=code), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / 'audit'
                with patch('pm_scraper.coverage_check.cli.main', side_effect=fake_run):
                    self.assertEqual(check('noesis', target), 1)
                self.assertFalse((target / 'source-health.json').exists())

    def test_existing_artifact_directory_is_never_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch('pm_scraper.coverage_check.cli.main') as run:
                with self.assertRaises(FileExistsError):
                    check('noesis', temporary)
                run.assert_not_called()

    def test_summary_escapes_source_text(self):
        text = summary([dict(audit(), messages=['<script>x</script>\n| [link](x) `x`'])], 0)
        self.assertNotIn('<script>', text)
        self.assertNotIn('[link]', text)
        self.assertIn('&lt;script&gt;', text)
        self.assertIn('&#124;', text)

    def test_annotation_cannot_inject_another_workflow_command(self):
        self.assertEqual(annotation('100%\r\n::error::bad'), '100%25%0D%0A::error::bad')


if __name__ == '__main__':
    unittest.main()
