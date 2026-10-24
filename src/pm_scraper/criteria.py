"""Validate user-editable screening settings before retrieval or delivery."""
import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LANGUAGES = {
    'English': ('english', 'ingles'), 'Portuguese': ('portuguese', 'portugues'),
    'Spanish': ('spanish', 'espanhol', 'castellano'), 'German': ('german', 'alemao'),
    'French': ('french', 'frances'), 'Dutch': ('dutch', 'neerlandes'),
    'Italian': ('italian', 'italiano'), 'Polish': ('polish', 'polaco', 'polones'),
    'Czech': ('czech', 'checo'), 'Danish': ('danish', 'dinamarques'),
    'Swedish': ('swedish', 'sueco'), 'Norwegian': ('norwegian', 'noruegues'),
    'Finnish': ('finnish', 'finlandes'), 'Mandarin': ('mandarin', 'mandarim'),
    'Japanese': ('japanese', 'japones'), 'Arabic': ('arabic', 'arabe'),
}
LIMITS = {'max_post_age_days': (1, 30), 'max_office_days_per_week': (0, 5),
          'max_abroad_calendar_days_per_quarter': (0, 90),
          'max_distant_office_visits_per_quarter': (0, 12),
          'max_mandatory_experience_years': (0, 50)}
FLAGS = {'exclude_mandatory_coding': True, 'exclude_shift_on_call': True,
         'include_potential_matches': True, 'include_unknown_freshness': False,
         'include_future_dated': False, 'accept_employer_dates': False,
         'require_portugal_eligibility': False}
LISTS = {'allowed_languages', 'nearby_locations', 'excluded_companies',
         'explicit_inclusions', 'role_families', 'notes', 'allowed_residence_locations'}


def validate(cfg):
    if not isinstance(cfg, dict):
        raise ValueError('Criteria must be a JSON object')
    known = set(LIMITS) | set(FLAGS) | LISTS | {'timezone', 'home', 'portuguese_titles', 'experience_growth_anchor'}
    unknown = set(cfg) - known
    if unknown:
        raise ValueError('Unknown criteria setting(s): ' + ', '.join(sorted(unknown)))
    for key, (low, high) in LIMITS.items():
        if type(cfg.get(key)) is not int or not low <= cfg[key] <= high:
            raise ValueError(f'{key} must be an integer from {low} to {high}')
    for key, default in FLAGS.items():
        if type(cfg.get(key, default)) is not bool:
            raise ValueError(f'{key} must be true or false')
    if 'experience_growth_anchor' in cfg:
        value = cfg['experience_growth_anchor']
        try:
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('experience_growth_anchor must be a calendar date in YYYY-MM-DD format') from None
    for key in LISTS:
        values = cfg.get(key)
        if not isinstance(values, list) or not all(isinstance(x, str) and x.strip() for x in values):
            raise ValueError(f'{key} must be a list of nonempty strings')
        if len({x.casefold().strip() for x in values}) != len(values):
            raise ValueError(f'{key} contains duplicate values')
    if not cfg['role_families'] or not cfg['allowed_languages'] or not cfg['allowed_residence_locations']:
        raise ValueError('role_families, allowed_languages and allowed_residence_locations cannot be empty')
    unsupported = set(cfg['allowed_languages']) - set(LANGUAGES)
    if unsupported:
        raise ValueError('Unsupported language name(s): ' + ', '.join(sorted(unsupported)))
    aliases = cfg.get('portuguese_titles')
    if not isinstance(aliases, dict) or not all(isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip() for k, v in aliases.items()):
        raise ValueError('portuguese_titles must map titles to role families')
    if not isinstance(cfg.get('home'), str) or not cfg['home'].strip():
        raise ValueError('home must be nonempty text')
    try:
        ZoneInfo(cfg.get('timezone', ''))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError('timezone must be a valid IANA timezone') from None
    return {**cfg, **{key: cfg.get(key, default) for key, default in FLAGS.items()}}


def load(path):
    return validate(json.loads(Path(path).read_text()))


def experience_ceiling(cfg, now):
    """One additional year per completed local anniversary; absent anchor is fixed."""
    base = cfg['max_mandatory_experience_years']
    if 'experience_growth_anchor' not in cfg:
        return base
    anchor = date.fromisoformat(cfg['experience_growth_anchor'])
    today = now.astimezone(ZoneInfo(cfg['timezone'])).date()
    elapsed = today.year - anchor.year - ((today.month, today.day) < (anchor.month, anchor.day))
    return base + max(0, elapsed)


def freshness_days(source, override=None):
    cfg = load(Path(source) / 'config/criteria.json')
    if override is not None:
        cfg = validate({**cfg, 'max_post_age_days': override})
    return cfg['max_post_age_days']
