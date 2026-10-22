"""Explicit residence requirements take precedence over remote/location labels."""
import re
from .htmlutil import norm


def incompatible_residence(text, allowed_locations):
    allowed = {norm(x) for x in allowed_locations}
    # These broad scopes include the candidate's existing northern Portugal home.
    allowed |= {'portugal', 'northern portugal', 'north portugal', 'norte de portugal',
                'europe', 'eu', 'european union', 'eea', 'european economic area'}
    verb = r'(?:live|reside|be (?:based|located|resident|living|residing)|relocate|move)'
    patterns = [
        rf'\b(?:must|need to|needs to|required to|have to|has to|are expected to)\s+(?:(?:currently|already)\s+)?{verb}\s+(?:in|to|near|within|local to)\s+(.+)',
        rf'\brequires?\s+(?:you|the candidate|candidates?|applicants?)\s+to\s+{verb}\s+(?:in|to|near|within|local to)\s+(.+)',
        r'\bonly\s+(?:candidates?|applicants?)\s+(?:(?:who\s+)?are\s+)?(?:based|located|resident)\s+in\s+(.+)',
        r'\b(?:residence|residency|relocation)\s+(?:in|to)\s+(.+?)\s+(?:is\s+)?(?:required|mandatory)\b',
        r'\b(?:deve|devem|tem de|necessario|obrigatorio)\s+(?:atualmente\s+)?(?:residir|morar|viver|estar localizado)\s+(?:em|no|na)\s+(.+)',
        r'\b(?:residencia|relocalizacao|mudanca)\s+obrigatoria\s+(?:em|para|no|na)\s+(.+)',
        r'\b(?:residencia|relocalizacao)\s+(?:em|para)\s+(.+?)\s+(?:e\s+)?(?:obrigatoria|necessaria)\b',
    ]
    failures = []
    for original in re.split(r'[\n;.!?]+', text):
        clause = norm(original)
        if not clause:
            continue
        for pattern in patterns:
            for match in re.finditer(pattern, clause):
                prefix = clause[max(0, match.start()-20):match.start()]
                if re.search(r'\b(?:not|never|nao|sem)\s*$', prefix):
                    continue
                requirement = match.group(0).split(',')[0]
                if re.search(r'\b(?:preferred|optional|not required|not mandatory|opcional|preferencial|nao obrigatoria)\b', requirement):
                    continue
                place = match.group(1).strip(' ,:')
                place = re.sub(r'\s+(?:will|can)\s+be\s+considered\b.*$', '', place)
                # A numeric UTC/GMT range is a work-hours constraint, not a
                # requirement to reside in a particular city or country.
                if re.match(r'^(?:[+-]?\d+(?::\d+)?\s*[/–—-]\s*[+-]?\d+(?::\d+)?\s*(?:utc|gmt)\b|(?:utc|gmt)\b)', place):
                    continue
                # Alternatives explicitly admitting Porto/Braga are compatible.
                alternatives = re.split(r'\s+(?:or|ou)\s+|/', place)
                compatible = False
                for alternative in alternatives:
                    location = re.split(r',|\s+(?:and|e|with|com|for|para|to)\s+|\s*\(', alternative)[0].strip()
                    location = re.sub(r'^(?:the\s+)?(?:city|district|area|region|cidade|distrito|zona|regiao)\s+(?:of|de)\s+', '', location)
                    location = re.sub(r'^the\s+', '', location)
                    location = re.sub(r'\s+(?:area|region|district|metropolitan area|city)$', '', location)
                    if location in allowed:
                        compatible = True
                if not compatible:
                    failures.append(original.strip())
    return list(dict.fromkeys(failures))
