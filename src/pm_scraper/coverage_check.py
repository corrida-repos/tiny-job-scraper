"""Disposable, read-only coverage diagnostics for the five unresolved sources."""
import argparse
import html
import json
import os
import tempfile
from pathlib import Path

from . import cli

GAPS = ('cocus', 'float', 'jta-the-data-scientists', 'namecheap', 'noesis')


def selected_sources(selection):
    if selection == 'all-gaps':
        return GAPS
    if selection not in GAPS:
        raise ValueError('Unknown coverage-check employer')
    return (selection,)


def validate_health(health, expected, exit_code):
    """Exit 2 means incomplete only when a full, consistent audit exists."""
    if exit_code not in (0, 2):
        raise ValueError(f'Scraper execution failed (exit {exit_code})')
    if not isinstance(health, list) or len(health) != len(expected):
        raise ValueError('Missing or unexpected source audit')
    if {row.get('company_id') for row in health if isinstance(row, dict)} != set(expected):
        raise ValueError('Source audit does not match the requested employers')
    for row in health:
        if type(row.get('complete')) is not bool or not isinstance(row.get('status'), str):
            raise ValueError('Invalid source status')
        if row['complete'] != (row['status'] == 'ok'):
            raise ValueError('Inconsistent source status')
        for field in ('discovered', 'pages', 'candidates'):
            if type(row.get(field)) is not int or row[field] < 0:
                raise ValueError('Invalid source counts')
        if not isinstance(row.get('company'), str) or not isinstance(row.get('messages'), list):
            raise ValueError('Invalid source diagnostic')
        if not all(isinstance(message, str) for message in row['messages']):
            raise ValueError('Invalid source messages')
    complete = sum(row['complete'] for row in health)
    if exit_code != (0 if complete == len(expected) else 2):
        raise ValueError('Scraper exit code contradicts coverage audit')
    return complete


def cell(value):
    # Source messages are untrusted text, not Markdown, HTML or Actions commands.
    return ''.join(f'&#{ord(c)};' if c in '|`*_[]\\' else html.escape(c)
                   for c in ' '.join(str(value).split()))


def annotation(value):
    return str(value).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


def summary(health, complete):
    lines = ['## Focused coverage check', '',
             f'**{complete}/{len(health)} source scopes complete; '
             f'{len(health) - complete} need attention.**', '',
             'A successful diagnostic job does not mean complete employer coverage. '
             'Disposable database; no email or production-state writes. Freshness: 48 hours.', '',
             '| Employer | Status | Listed | Candidates | Pages/requests | Reasons |',
             '| --- | --- | ---: | ---: | ---: | --- |']
    for row in health:
        values = [row['company'], row['status'], row['discovered'], row['candidates'],
                  row['pages'], '; '.join(row['messages'])]
        lines.append('| ' + ' | '.join(cell(v) for v in values) + ' |')
    return '\n'.join(lines) + '\n'


def check(selection, artifact_dir, summary_path=None):
    expected = selected_sources(selection)
    artifact_dir = Path(artifact_dir)
    # Refuse reused destinations, so stale health cannot masquerade as this run.
    artifact_dir.mkdir(parents=True, exist_ok=False)
    try:
        with tempfile.TemporaryDirectory(prefix='tiny-coverage-') as temporary:
            root = Path(temporary)
            code = cli.main(['run', '--only', ','.join(expected),
                             '--state', str(root / 'state.sqlite3'),
                             '--output', str(root / 'output'), '--max-post-age-days', '2'])
            health = json.loads((root / 'output/source-health.json').read_text())
            complete = validate_health(health, expected, code)
            (artifact_dir / 'source-health.json').write_text(
                json.dumps(health, ensure_ascii=False, indent=2) + '\n')
            report = summary(health, complete)
        # Only the audit survives; SQLite, job details and email drafts are discarded.
        (artifact_dir / 'summary.md').write_text(report)
        if summary_path:
            with Path(summary_path).open('a') as output:
                output.write(report)
        print(f'::notice::Coverage check: {complete}/{len(expected)} complete; '
              f'{len(expected) - complete} need attention. No email or production-state writes.')
        for row in health:
            level = 'notice' if row['complete'] else 'warning'
            detail = (f"{row['company']}: {row['status']}; {row['discovered']} listed; "
                      f"{row['candidates']} candidates; {row['pages']} pages/requests. "
                      + '; '.join(row['messages']))
            print(f'::{level}::' + annotation(detail))
        return 0
    except (OSError, ValueError, TypeError) as error:
        report = '## Coverage check failed\n\nExecution/audit failure: ' + cell(error) + '\n'
        (artifact_dir / 'summary.md').write_text(report)
        if summary_path:
            with Path(summary_path).open('a') as output:
                output.write(report)
        print('Coverage check failed: ' + type(error).__name__)
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=('all-gaps',) + GAPS, default='all-gaps')
    parser.add_argument('--artifact-dir', required=True, help='New directory for audit artifacts')
    args = parser.parse_args(argv)
    return check(args.source, args.artifact_dir, os.environ.get('GITHUB_STEP_SUMMARY'))


if __name__ == '__main__':
    raise SystemExit(main())
