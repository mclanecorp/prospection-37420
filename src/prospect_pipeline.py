#!/usr/bin/env python3
import argparse
import base64
import csv
import html
import json
import os
import re
import textwrap
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import quote, urlparse

USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) HermesAgent/1.0'
OVERPASS_URLS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
]
NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
SOCIAL_OR_DIRECTORY_DOMAINS = {
    'facebook.com', 'm.facebook.com', 'instagram.com', 'pagesjaunes.fr', 'hoodspot.fr',
    'linternaute.com', 'mapcarta.com', 'gralon.net', 'petitfute.com', 'tripadvisor.fr',
    'tripadvisor.com', 'yelp.com', 'mappy.com', 'justacote.com', 'horaires.lefigaro.fr',
    'societe.com', 'verif.com', 'manageo.fr', 'annuaire-mairie.fr', 'contact-banque.com', '118000.fr'
}
GENERIC_BRANDS = {
    'carrefour', 'intermarche', 'vival', 'spar', 'gamm vert', 'groupama',
    'credit agricole', 'lcl', 'banque populaire', 'caisse d epargne', 'orano', 'adecco'
}


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def simplify(value):
    normalized = unicodedata.normalize('NFKD', str(value or ''))
    ascii_value = normalized.encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9 ]+', ' ', ascii_value.lower()).strip()


def http_get_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    delay = 2.0
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 3:
                raise
            time.sleep(delay)
            delay *= 2


def http_post_json(url, form_data):
    body = urllib.parse.urlencode(form_data).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            'User-Agent': USER_AGENT,
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def fetch_postcode_nominatim_results(postal_code, country='France'):
    params = urllib.parse.urlencode({'q': f'{postal_code} {country}', 'format': 'jsonv2', 'limit': 10})
    return http_get_json(f'{NOMINATIM_URL}?{params}')


def postal_cache_path(outdir_root):
    return os.path.join(outdir_root, 'config', 'postal_codes.json')


def load_postal_code_cache(outdir_root):
    path = postal_cache_path(outdir_root)
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def save_postal_code_cache(outdir_root, cache):
    path = postal_cache_path(outdir_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=2)


def build_job_config(postal_code, outdir_root, nominatim_results):
    postal_code = clean(postal_code)
    for result in nominatim_results:
        if result.get('osm_type') == 'relation' and result.get('type') == 'postal_code':
            relation_id = int(result['osm_id'])
            return {
                'postal_code': postal_code,
                'relation_id': relation_id,
                'area_id': 3600000000 + relation_id,
                'label': postal_code,
                'job_dir': os.path.join(outdir_root, postal_code),
                'display_name': clean(result.get('display_name')),
            }
    raise ValueError(f'Aucune relation Nominatim exploitable trouvée pour le code postal {postal_code}')


def resolve_job_config(postal_code, outdir_root, country='France'):
    postal_code = clean(postal_code)
    cache = load_postal_code_cache(outdir_root)
    cached = cache.get(postal_code)
    if cached:
        config = dict(cached)
        config['job_dir'] = os.path.join(outdir_root, postal_code)
        return config
    config = build_job_config(postal_code, outdir_root, fetch_postcode_nominatim_results(postal_code, country=country))
    cache[postal_code] = {
        'postal_code': config['postal_code'],
        'relation_id': config['relation_id'],
        'area_id': config['area_id'],
        'label': config['label'],
        'display_name': config['display_name'],
    }
    save_postal_code_cache(outdir_root, cache)
    return config


def build_output_paths(config):
    postal_code = config['postal_code']
    job_dir = config['job_dir']
    return {
        'job_dir': job_dir,
        'data_dir': os.path.join(job_dir, 'data'),
        'reports_dir': os.path.join(job_dir, 'reports'),
        'json': os.path.join(job_dir, 'data', f'{postal_code}.json'),
        'csv': os.path.join(job_dir, 'data', f'{postal_code}.csv'),
        'targets_json': os.path.join(job_dir, 'data', f'{postal_code}_targets_without_clear_website.json'),
        'targets_csv': os.path.join(job_dir, 'data', f'{postal_code}_targets_without_clear_website.csv'),
        'html': os.path.join(job_dir, 'reports', f'{postal_code}.html'),
        'readme': os.path.join(job_dir, 'README.md'),
    }


def fetch_overpass_elements(config):
    query = textwrap.dedent(f'''
    [out:json][timeout:90];
    area({config['area_id']})->.a;
    (
      nwr(area.a)[shop];
      nwr(area.a)[craft];
      nwr(area.a)[office];
      nwr(area.a)[tourism~"^(hotel|guest_house|motel|camp_site|chalet|museum|attraction)$"];
      nwr(area.a)[amenity~"^(restaurant|cafe|bar|pub|fast_food|bank|pharmacy|clinic|dentist|doctors|veterinary|car_repair|car_rental|fuel|marketplace)$"];
    );
    out center tags;
    ''').strip()
    last_error = None
    for url in OVERPASS_URLS:
        try:
            payload = http_post_json(url, {'data': query})
            return payload.get('elements', [])
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f'Overpass failed: {last_error}')


def business_type(tags):
    for key in ['shop', 'craft', 'office', 'tourism', 'amenity']:
        if tags.get(key):
            return f'{key}:{tags.get(key)}'
    return ''


def subcategory(tags):
    for key in ['shop', 'craft', 'office', 'tourism', 'amenity']:
        if tags.get(key):
            return tags.get(key)
    return ''


def website_from_tags(tags):
    for key in ['website', 'contact:website', 'url']:
        value = clean(tags.get(key))
        if value:
            return value
    return ''


def email_from_tags(tags):
    for key in ['email', 'contact:email']:
        value = clean(tags.get(key))
        if value:
            return value
    return ''


def phone_from_tags(tags):
    for key in ['phone', 'contact:phone']:
        value = clean(tags.get(key))
        if value:
            return value
    return ''


def address_from_tags(tags):
    parts = []
    line1 = ' '.join(x for x in [clean(tags.get('addr:housenumber')), clean(tags.get('addr:street'))] if x)
    if line1:
        parts.append(line1)
    line2 = ' '.join(x for x in [clean(tags.get('addr:postcode')), clean(tags.get('addr:city'))] if x)
    if line2:
        parts.append(line2)
    if not parts and clean(tags.get('addr:place')):
        parts.append(clean(tags.get('addr:place')))
    return ', '.join(parts)


def commune_from_tags(tags):
    for key in ['addr:city', 'addr:municipality']:
        value = clean(tags.get(key))
        if value:
            return value
    return ''


def commune_from_reverse_address(address):
    for key in ['city', 'town', 'village', 'municipality']:
        value = clean(address.get(key))
        if value:
            return value
    return ''


def formatted_reverse_address(address):
    house_number = clean(address.get('house_number'))
    road = clean(address.get('road'))
    postcode = clean(address.get('postcode'))
    commune = commune_from_reverse_address(address)
    line1 = ' '.join(part for part in [house_number, road] if part)
    line2 = ' '.join(part for part in [postcode, commune] if part)
    parts = [part for part in [line1, line2] if part]
    return ', '.join(parts)


def fetch_reverse_geocode(lat, lon):
    params = urllib.parse.urlencode({'lat': lat, 'lon': lon, 'format': 'jsonv2'})
    url = f'https://nominatim.openstreetmap.org/reverse?{params}'
    return http_get_json(url)


def enrich_record_from_reverse_geocode(record, reverse_result):
    address = reverse_result.get('address', {})
    if not record.get('address'):
        reverse_address = formatted_reverse_address(address)
        if reverse_address:
            record['address'] = reverse_address
    if not record.get('commune'):
        commune = commune_from_reverse_address(address)
        if commune:
            record['commune'] = commune
    postcode = clean(address.get('postcode'))
    if postcode and clean(record.get('postal_code')) != postcode:
        record['postal_code'] = postcode


def search_web(query):
    url = 'https://www.bing.com/search?q=' + quote(query) + '&setlang=fr'
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode('utf-8', 'ignore')


def decode_bing_href(href):
    href = html.unescape(href)
    match = re.search(r'[?&]u=([^&]+)', href)
    if not match:
        return href
    encoded = urllib.parse.unquote(match.group(1))
    if not encoded.startswith('a1'):
        return href
    raw = encoded[2:]
    raw += '=' * ((4 - len(raw) % 4) % 4)
    try:
        return base64.b64decode(raw).decode('utf-8', 'ignore')
    except Exception:
        return href


def extract_search_results(page_html):
    matches = re.findall(r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page_html, re.S)
    results = []
    for href, title_html in matches[:5]:
        url = clean(decode_bing_href(href))
        title = html.unescape(re.sub(r'<.*?>', '', title_html))
        results.append({'url': url, 'title': clean(title)})
    return results


def domain_of(url):
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith('www.') else host


def is_social_or_directory(url):
    return domain_of(url) in SOCIAL_OR_DIRECTORY_DOMAINS


def looks_official(name, url, title=''):
    host = re.sub(r'[^a-z0-9]+', '', domain_of(url))
    normalized_name = simplify(name)
    compact_name = re.sub(r'[^a-z0-9]+', '', normalized_name)
    if any(brand in normalized_name for brand in GENERIC_BRANDS):
        return True
    tokens = [token for token in normalized_name.split() if len(token) >= 4]
    if any(re.sub(r'[^a-z0-9]+', '', token) in host for token in tokens):
        return True
    if len(compact_name) >= 7 and compact_name[:10] in host:
        return True
    compact_title = re.sub(r'[^a-z0-9]+', '', simplify(title))
    return bool(compact_name and compact_name[:8] in compact_title)


def query_variants(record):
    commune = record.get('commune') or record.get('postal_code') or ''
    variants = [
        f'"{record["name"]}" {commune} site officiel',
        f'{record["name"]} {commune}',
        f'{simplify(record["name"])} {commune}',
    ]
    unique = []
    for variant in variants:
        variant = clean(variant)
        if variant and variant not in unique:
            unique.append(variant)
    return unique


def classify_website(record):
    if record['website']:
        record['website_status'] = 'yes'
        record['website_confidence'] = 'high'
        record['website_evidence'] = 'website tag présent dans OpenStreetMap'
        return

    best = None
    for query in query_variants(record):
        try:
            results = extract_search_results(search_web(query))
        except Exception:
            continue
        if not results:
            continue
        top_result = results[0]
        top_url = top_result['url']
        top_domain = domain_of(top_url)
        if looks_official(record['name'], top_url, top_result['title']):
            best = ('likely_yes', 'medium', top_url, f'premier domaine plausible comme site officiel ({top_domain})', results)
            break
        if is_social_or_directory(top_url):
            best = ('no', 'medium', '', f'premier résultat = annuaire/réseau social ({top_domain})', results)
            break
        if best is None:
            best = ('uncertain', 'low', '', f'résultat ambigu ({top_domain})', results)

    if best is None:
        record['website_status'] = 'uncertain'
        record['website_confidence'] = 'low'
        record['website_evidence'] = 'aucun résultat web exploitable'
        record['search_results'] = []
        return

    status, confidence, website, evidence, results = best
    record['website_status'] = status
    record['website_confidence'] = confidence
    record['website_evidence'] = evidence
    record['search_results'] = results
    if website:
        record['website'] = website


def prospect_score(record):
    score = 0
    if record['website_status'] == 'no':
        score += 3
    elif record['website_status'] == 'uncertain':
        score += 1
    if record['phone']:
        score += 2
    if record['email']:
        score += 2
    if record['address']:
        score += 1
    return score


def build_records(elements, postal_code):
    records = []
    seen = set()
    for element in elements:
        tags = element.get('tags', {})
        name = clean(tags.get('name'))
        if not name:
            continue
        lat = element.get('lat') or element.get('center', {}).get('lat')
        lon = element.get('lon') or element.get('center', {}).get('lon')
        key = (name.lower(), round(float(lat), 5) if lat else None, round(float(lon), 5) if lon else None)
        if key in seen:
            continue
        seen.add(key)
        records.append({
            'id': f"{element.get('type')}:{element.get('id')}",
            'name': name,
            'category': business_type(tags),
            'subcategory': subcategory(tags),
            'commune': commune_from_tags(tags),
            'postal_code': clean(tags.get('addr:postcode')) or postal_code,
            'address': address_from_tags(tags),
            'phone': phone_from_tags(tags),
            'email': email_from_tags(tags),
            'website': website_from_tags(tags),
            'lat': lat,
            'lon': lon,
            'opening_hours': clean(tags.get('opening_hours')),
            'source': 'OpenStreetMap',
            'source_url': f"https://www.openstreetmap.org/{element.get('type')}/{element.get('id')}",
            'maps_url': f"https://www.google.com/maps/search/?api=1&query={lat},{lon}",
            'website_status': '',
            'website_confidence': '',
            'website_evidence': '',
            'search_results': [],
            'priority': '',
            'prospect_score': 0,
        })
    return records


def enrich_records_with_reverse_geocoding(records, sleep_seconds=1.0):
    reverse_cache = {}
    for record in records:
        lat = record.get('lat')
        lon = record.get('lon')
        if lat is None or lon is None:
            continue
        cache_key = (round(float(lat), 6), round(float(lon), 6))
        if cache_key not in reverse_cache:
            try:
                reverse_cache[cache_key] = fetch_reverse_geocode(lat, lon)
            except Exception:
                continue
            if sleep_seconds:
                time.sleep(sleep_seconds)
        enrich_record_from_reverse_geocode(record, reverse_cache[cache_key])


def summarize(records):
    return {
        'total': len(records),
        'no': sum(1 for record in records if record['website_status'] == 'no'),
        'uncertain': sum(1 for record in records if record['website_status'] == 'uncertain'),
        'yes': sum(1 for record in records if record['website_status'] == 'yes'),
        'likely_yes': sum(1 for record in records if record['website_status'] == 'likely_yes'),
    }


def target_records(records):
    return [record for record in records if record['website_status'] in ('no', 'uncertain')]


def write_outputs(config, records):
    paths = build_output_paths(config)
    os.makedirs(paths['data_dir'], exist_ok=True)
    os.makedirs(paths['reports_dir'], exist_ok=True)

    with open(paths['json'], 'w', encoding='utf-8') as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)

    columns = [
        'name', 'subcategory', 'category', 'commune', 'postal_code', 'address', 'phone', 'email',
        'website_status', 'website_confidence', 'website', 'priority', 'prospect_score', 'opening_hours',
        'source', 'source_url', 'maps_url', 'website_evidence'
    ]
    with open(paths['csv'], 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow({column: record.get(column, '') for column in columns})

    targets = target_records(records)
    target_columns = [
        'name', 'subcategory', 'category', 'commune', 'postal_code', 'address', 'phone', 'email',
        'website_status', 'website_confidence', 'priority', 'prospect_score', 'opening_hours',
        'source_url', 'maps_url', 'website_evidence'
    ]
    with open(paths['targets_csv'], 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=target_columns)
        writer.writeheader()
        for record in targets:
            writer.writerow({column: record.get(column, '') for column in target_columns})
    with open(paths['targets_json'], 'w', encoding='utf-8') as handle:
        json.dump(targets, handle, ensure_ascii=False, indent=2)

    summary = summarize(records)
    rows = []
    for record in targets:
        contact = ' / '.join([value for value in [record['phone'], record['email']] if value]) or '—'
        kind = record['subcategory'] + (f" · {record['commune']}" if record['commune'] else '')
        rows.append(
            f"<tr>"
            f"<td>{html.escape(record['name'])}</td>"
            f"<td>{html.escape(kind or '—')}</td>"
            f"<td>{html.escape(record['address'] or '—')}</td>"
            f"<td>{html.escape(contact)}</td>"
            f"<td><span class='badge {record['website_status']}'>{html.escape(record['website_status'])}</span></td>"
            f"<td>{html.escape(record['website_evidence'])}</td>"
            f"<td>{html.escape(record['priority'])} ({record['prospect_score']})</td>"
            f"<td><a href='{html.escape(record['maps_url'])}'>Maps</a> | <a href='{html.escape(record['source_url'])}'>OSM</a></td>"
            f"</tr>"
        )

    postal_code = config['postal_code']
    page = f'''<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Prospection {postal_code}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; background: #111827; color: #e5e7eb; }}
    h1, h2 {{ color: #fff; }}
    a {{ color: #93c5fd; }}
    .card {{ display: inline-block; background: #1f2937; padding: 12px 16px; margin-right: 10px; margin-bottom: 10px; border-radius: 10px; }}
    table {{ width: 100%; border-collapse: collapse; background: #0f172a; }}
    th, td {{ border: 1px solid #334155; padding: 8px; vertical-align: top; }}
    th {{ background: #1e293b; position: sticky; top: 0; }}
    .badge {{ padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: bold; }}
    .no {{ background: #7f1d1d; }}
    .uncertain {{ background: #92400e; }}
    .yes, .likely_yes {{ background: #166534; }}
    input {{ padding: 8px; width: 360px; margin: 12px 0; background: #111827; color: #fff; border: 1px solid #475569; border-radius: 8px; }}
    .small {{ color: #94a3b8; }}
  </style>
  <script>
    function filterRows() {{
      const q = document.getElementById('q').value.toLowerCase();
      for (const tr of document.querySelectorAll('tbody tr')) {{
        tr.style.display = tr.innerText.toLowerCase().includes(q) ? '' : 'none';
      }}
    }}
  </script>
</head>
<body>
  <h1>Prospection entreprises — code postal {postal_code}</h1>
  <p class="small">Collecte automatique depuis OpenStreetMap + vérification Bing légère. Cette page cible les entreprises sans site clair ou à vérifier.</p>
  <div class="card">Total entreprises : <b>{summary['total']}</b></div>
  <div class="card">Sans site : <b>{summary['no']}</b></div>
  <div class="card">À vérifier : <b>{summary['uncertain']}</b></div>
  <div class="card">Site trouvé via OSM : <b>{summary['yes']}</b></div>
  <div class="card">Site probable : <b>{summary['likely_yes']}</b></div>
  <h2>Cibles sans site clair</h2>
  <input id="q" oninput="filterRows()" placeholder="Filtrer par nom, ville, activité...">
  <table>
    <thead>
      <tr>
        <th>Entreprise</th>
        <th>Type</th>
        <th>Adresse</th>
        <th>Contact</th>
        <th>Site</th>
        <th>Justification</th>
        <th>Priorité</th>
        <th>Liens</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>'''
    with open(paths['html'], 'w', encoding='utf-8') as handle:
        handle.write(page)

    with open(paths['readme'], 'w', encoding='utf-8') as handle:
        handle.write(
            f'# Prospection {postal_code}\n\n'
            f'Collecte automatique des entreprises du code postal {postal_code} pour usage de prospection web.\n\n'
            '## Fichiers\n'
            f'- `data/{postal_code}.json` : données complètes\n'
            f'- `data/{postal_code}.csv` : export tabulaire\n'
            f'- `data/{postal_code}_targets_without_clear_website.csv` : cibles prioritaires\n'
            f'- `reports/{postal_code}.html` : rapport HTML filtrable\n\n'
            '## Méthode\n'
            '- extraction des points business via OpenStreetMap / Overpass\n'
            '- détection du site via tags OSM quand présents\n'
            '- sinon recherche web légère pour classer `no`, `uncertain`, `likely_yes`\n\n'
            '## Limites\n'
            '- la couverture dépend des données OSM\n'
            '- l\'absence de site est une inférence, pas une preuve absolue\n'
            '- certaines entreprises locales peuvent manquer si non cartographiées\n'
        )

    return summary


def run_collection(postal_code, outdir_root, country='France', sleep_seconds=0.15):
    config = resolve_job_config(postal_code, outdir_root, country=country)
    os.makedirs(config['job_dir'], exist_ok=True)
    elements = fetch_overpass_elements(config)
    records = build_records(elements, postal_code=config['postal_code'])
    for index, record in enumerate(records, start=1):
        classify_website(record)
        record['prospect_score'] = prospect_score(record)
        if record['website_status'] == 'no' and (record['phone'] or record['email']):
            record['priority'] = 'high'
        elif record['website_status'] in ('no', 'uncertain'):
            record['priority'] = 'medium'
        else:
            record['priority'] = 'low'
        if sleep_seconds:
            if index % 20 == 0:
                time.sleep(max(1.0, sleep_seconds * 8))
            else:
                time.sleep(sleep_seconds)
    enrich_records_with_reverse_geocoding(target_records(records), sleep_seconds=1.0)
    for record in records:
        record['prospect_score'] = prospect_score(record)
        if record['website_status'] == 'no' and (record['phone'] or record['email']):
            record['priority'] = 'high'
        elif record['website_status'] in ('no', 'uncertain'):
            record['priority'] = 'medium'
        else:
            record['priority'] = 'low'
    records.sort(key=lambda item: (-item['prospect_score'], item['name'].lower()))
    summary = write_outputs(config, records)
    top_non_site = [
        {
            'name': record['name'],
            'subcategory': record['subcategory'],
            'commune': record['commune'],
            'contact': record['phone'] or record['email'],
            'website_status': record['website_status'],
            'priority': record['priority'],
            'website': record['website'],
        }
        for record in target_records(records)
    ][:15]
    return {'config': config, 'summary': summary, 'top_non_site': top_non_site, 'paths': build_output_paths(config)}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Collecte de prospects locaux par code postal')
    parser.add_argument('--postal-code', required=True, help='Code postal à analyser, ex: 37420')
    parser.add_argument('--outdir-root', default=os.path.dirname(os.path.dirname(__file__)), help='Dossier racine de sortie')
    parser.add_argument('--country', default='France', help='Pays pour la résolution Nominatim')
    parser.add_argument('--sleep-seconds', type=float, default=0.15, help='Pause entre recherches web')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    result = run_collection(args.postal_code, args.outdir_root, country=args.country, sleep_seconds=args.sleep_seconds)
    print(json.dumps({'summary': result['summary'], 'top_non_site': result['top_non_site'], 'job_dir': result['config']['job_dir']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
