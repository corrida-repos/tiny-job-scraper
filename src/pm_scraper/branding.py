"""Versioned official-site icons, displayed inline and embedded in HTML email."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT/'config' if (ROOT/'config').is_dir() else Path(sys.prefix)/'share/pm-career-scraper/config'
ASSETS = ROOT/'assets/company-logos' if (ROOT/'assets/company-logos').is_dir() else Path(sys.prefix)/'share/pm-career-scraper/assets/company-logos'
URL_BASE = 'https://raw.githubusercontent.com/corrida-repos/tiny-job-scraper/main/assets/company-logos/'


def logos():
    manifest = CONFIG/'company-logos.json'
    if not manifest.is_file():
        return {}
    entries = json.loads(manifest.read_text())
    return {company: ASSETS/(company+'.png') for company, entry in entries.items()
            if re.fullmatch(r'[a-z0-9-]+', company)
            and entry.get('file') == 'assets/company-logos/'+company+'.png'
            and (ASSETS/(company+'.png')).is_file()}


def company_heading(company_id, company_name):
    if company_id in logos():
        return f'## ![Company logo]({URL_BASE}{company_id}.png) {company_name}'
    return f'## {company_name}'


def render_email_html(markdown, embed=True):
    from markdown_it import MarkdownIt
    rendered = MarkdownIt('commonmark', {'html': False}).render(markdown)
    attachments = []
    manifest = CONFIG/'company-logos.json'
    entries = json.loads(manifest.read_text()) if manifest.is_file() else {}
    for company, path in logos().items():
        source = f'src="{URL_BASE}{company}.png"'
        if source not in rendered:
            continue
        cid = 'tiny-logo-'+company
        replacement = f'src="cid:{cid}"' if embed else source
        width = entries[company].get('display_width', 32)
        height = entries[company].get('display_height', 32)
        if type(width) is not int or type(height) is not int or not 1 <= width <= 128 or not 1 <= height <= 64:
            width = height = 32
        replacement += f' width="{width}" height="{height}" style="width:{width}px;height:{height}px;vertical-align:middle;margin-right:8px;object-fit:contain"'
        rendered = rendered.replace(source, replacement)
        if embed:
            attachments.append((cid, path.read_bytes()))
    return rendered, attachments
