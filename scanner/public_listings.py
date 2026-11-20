"""Read an official vacancy index, then JobPosting metadata for relevant India roles."""
import json
import re
from urllib.parse import unquote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from . import ats
from .common import Throttled, clean_text, now_utc, parse_iso


def scan(http, emp, settings, budget):
    cfg = emp['ats']
    url = cfg['url']
    host = urlsplit(url).netloc
    rows = []
    status = {'state': 'error', 'scope': cfg['format'], 'listings_read': False, 'india_observed': None}
    robots = RobotFileParser()

    def request(link, *, check_policy=True, data=None):
        if budget.spent:
            raise TimeoutError('phase budget exhausted')
        if urlsplit(link).netloc != host or urlsplit(link).scheme != 'https':
            raise ValueError('unexpected listing host')
        if check_policy and not robots.can_fetch('*', link):
            raise PermissionError('robots.txt')
        options = {'retries': 0, 'allow_redirects': False}
        response = http.post(link, data=data, **options) if data is not None else http.get(link, **options)
        if response.status_code in (401, 403, 429):
            raise PermissionError(f'HTTP {response.status_code}')
        return response

    try:
        policy = request(urljoin(url, '/robots.txt'), check_policy=False)
        if policy.status_code not in (200, 404):
            raise ValueError(f'robots.txt HTTP {policy.status_code}')
        robots.parse(policy.text.splitlines() if policy.status_code == 200 else [])
        # Do not proceed when the configured HTTP pacing cannot meet a declared delay.
        if robots.crawl_delay('*') or robots.request_rate('*'):
            raise PermissionError('site-specific crawl rate requires review')
        kind = cfg['format']
        form = {'action': 'fetch_job_listings', 'search': '', 'location': ''} if kind == 'voya_india' else None
        page = request(url, data=form)
        if page.status_code != 200:
            raise ValueError(f'index HTTP {page.status_code}')
        entries = {}
        if kind == 'workday_sitemap':
            root = ElementTree.fromstring(page.content)
            if root.tag.split('}')[-1] != 'urlset':
                raise ValueError('expected vacancy sitemap')
            for item in root.findall('{*}url'):
                link = item.findtext('{*}loc') or ''
                match = re.search(r'/job/([^/]+)/([^/]+)$', unquote(urlsplit(link).path))
                if match and urlsplit(link).netloc == host and urlsplit(link).scheme == 'https':
                    entries[link] = tuple(v.replace('-', ' ') for v in match.groups())
            if len(entries) != len(root):
                raise ValueError('unexpected or duplicate vacancy URLs')
        elif kind == 'featured_cards':
            for card in BeautifulSoup(page.content, 'html.parser').select('.job-list__content'):
                a, place = card.select_one('a.job-list__job-link[href]'), card.select_one('.job-desc-location')
                if not a or not place:
                    raise ValueError('unexpected vacancy card')
                entries[urljoin(url, a['href'])] = (place.get_text(strip=True), a.get_text(strip=True))
            if not entries:
                raise ValueError('no identifiable vacancy cards')
        elif kind == 'voya_india':
            table = BeautifulSoup(page.content, 'html.parser').select_one('table.jobtable')
            if not table or [th.get_text(strip=True) for th in table.select('th')] != ['Req ID', 'Title', 'Location']:
                raise ValueError('unexpected Voya listing table')
            for tr in table.select('tr'):
                cells = tr.select('td')
                if not cells:
                    continue
                link = cells[1].select_one('a[href]') if len(cells) == 3 else None
                if not link or not re.fullmatch(r'/career-inner-page/\d+/?', urlsplit(link['href']).path):
                    raise ValueError('unexpected Voya listing row')
                entries[urljoin(url, link['href'])] = (cells[2].get_text(strip=True), link.get_text(strip=True))
        else:
            raise ValueError('unsupported vacancy index')
        if any(urlsplit(link).scheme != 'https' or urlsplit(link).netloc != host for link in entries):
            raise ValueError('unexpected vacancy link host')
        india = {k: v for k, v in entries.items() if ats.INDIA.search(v[0])}
        candidates = [k for k, v in india.items() if ats.RELEVANT.search(v[1])]
        status.update(listings_read=True, pages=1, indexed=len(entries), india_observed=len(india), candidates=len(candidates))
        index_limited = kind == 'featured_cards' or (kind == 'workday_sitemap' and len(entries) >= 100)
        if index_limited:
            status['coverage_limit'] = 'featured postings only' if kind == 'featured_cards' else 'sitemap may stop at 100 jobs'
        if kind == 'voya_india':
            # The vacancy table does not expose a posting date; site-template metadata is not a job date.
            for link in candidates:
                place, title = india[link]
                rows.append(ats._row(emp['name'], title, place, link, urlsplit(link).path.rstrip('/').rsplit('/', 1)[-1], 'career_portal'))
            status.update(state='ok', returned=len(rows), date_available=False)
            return rows, status
        limit = settings['max_details_per_employer']
        for link in candidates[:limit]:
            detail = request(link)
            if detail.status_code != 200:
                raise ValueError(f'detail HTTP {detail.status_code}')
            scripts = BeautifulSoup(detail.content, 'html.parser').select('script[type="application/ld+json"]')
            job = next((j for tag in scripts for j in [json.loads(tag.get_text())]
                        if isinstance(j, dict) and j.get('@type') == 'JobPosting'), None)
            if not job or not job.get('title'):
                raise ValueError('missing JobPosting')
            locations = job.get('jobLocation') or []
            places = []
            for loc in locations if isinstance(locations, list) else [locations]:
                addr = loc.get('address') or {}
                country = addr.get('addressCountry')
                if isinstance(country, dict):
                    country = country.get('name')
                if str(country).lower() in ('india', 'in'):
                    places.append(', '.join(filter(None, [addr.get('addressLocality'), 'India'])))
            if not places:
                continue
            published = parse_iso(job.get('datePosted'))
            rows.append(ats._row(emp['name'], job['title'], places[0], link, link.rsplit('/', 1)[-1],
                                 'workday' if kind == 'workday_sitemap' else 'career_portal',
                                 posted_date=job['datePosted'] if published and published <= now_utc() else None,
                                 description=clean_text(job.get('description') or '')))
        status['state'] = 'capped' if index_limited or len(candidates) > limit else 'ok'
    except (Throttled, PermissionError) as exc:
        status.update(state='blocked', error=str(exc))
    except TimeoutError as exc:
        status.update(state='budget_exhausted', error=str(exc))
    except Exception as exc:
        status.update(state='partial' if status['listings_read'] else 'error', error=str(exc)[:200])
    status['returned'] = len(rows)
    return rows, status