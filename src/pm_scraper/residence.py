"""Explicit residence requirements take precedence over remote/location labels."""
import re
from .htmlutil import norm


def foreign_posting_location(location):
    """Dedicated ATS location labels, not incidental mentions in a description."""
    names = ('spain|espanha|greece|grecia|germany|alemanha|france|franca|italy|italia|'
             'poland|polonia|netherlands|belgium|austria|switzerland|ireland|united kingdom|uk|'
             'united states|usa|us|canada|brazil|brasil|mexico|argentina|colombia|'
             'india|japan|japao|china|singapore|australia|new zealand|south africa|'
             'thailand|malaysia|philippines|indonesia|vietnam|south korea|taiwan|'
             'denmark|sweden|norway|finland|iceland|estonia|latvia|lithuania|'
             'czech republic|czechia|slovakia|slovenia|croatia|romania|bulgaria|hungary|'
             'luxembourg|cyprus|malta|turkey|israel|united arab emirates|saudi arabia|'
             'madrid|barcelona|berlin|munich|paris|london|dublin|amsterdam|warsaw|'
             'athens|tokyo|bangalore|bengaluru|bangkok|toronto|sydney|new york')
    label = norm(location)
    # A multi-location label explicitly including Portugal is compatible.
    if re.search(r'\bportugal\b|\bporto\b|\bbraga\b', label):
        return False
    return bool(re.search(r'\b(?:'+names+r')\b', label))


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
        r'\b(?:this|the)\s+(?:role|position|job)\s+is\s+(?:only\s+)?(?:based|located)\s+in\s+(.+)',
        r'\b(?:candidates?|applicants?|you)\s+(?:should|must)\s+be\s+(?:based|located|resident)\s+in\s+(.+)',
        r'\b(?:only|exclusively)\s+(?:open|available)\s+to\s+(?:candidates?|applicants?|residents?)\s+(?:based\s+|located\s+|living\s+)?in\s+(.+)',
        r'\b(?:you|candidates?|applicants?)\s+(?:can|may)\s+(?:only\s+work|work\s+only)\s+(?:remotely\s+)?from\s+(.+)',
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
                alternatives = re.split(r'\s+(?:or|ou|and|e)\s+|/|,', place)
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
