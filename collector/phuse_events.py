"""Discover PHUSE events from official indexes; event dates are never publication dates."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urljoin, urlsplit
from clinical_sources import Result, soup, body_text, clean, parse_date, candidate, safe_error, TZ, DATE_RE

HOME = 'https://phuse.global/'
CALENDAR = 'https://phuse.global/Events_Calendar'
GROUPS = 'https://events.phuse.global/event/WorkingGroupEvents/events-calendar'
MAX_EVENTS = 40


def event_day(text):
    # A multi-day event belongs on its start day, not the last date in a printed range.
    normalized = re.sub(r'\b(\d{1,2})(?:st|nd|rd|th)?\s*[–—-]\s*\d{1,2}(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d{2})', r'\1 \2 \3', text)
    day = parse_date(normalized)
    if not day:
        return ''
    # Official pages often give parallel time zones. Prefer an explicit UTC/GMT time.
    times = re.findall(r'(\d{1,2}:\d{2})\s*(?:[–—-]\s*\d{1,2}:\d{2})?\s*\(?(EST|EDT|GMT|UTC|CET|CEST|BST)\)?', text)
    if times:
        clock, zone = next((x for x in times if x[1] in ('GMT', 'UTC')), times[0])
        offsets = {'EST': -5, 'EDT': -4, 'GMT': 0, 'UTC': 0, 'CET': 1, 'CEST': 2, 'BST': 1}
        dt = datetime.strptime(day + ' ' + clock, '%Y-%m-%d %H:%M')
        return dt.replace(tzinfo=timezone(timedelta(hours=offsets[zone]))).astimezone(TZ).date().isoformat()
    return day


def event_url(value, base):
    url = urljoin(base, value).split('#')[0]
    return url if urlsplit(url).scheme == 'https' and urlsplit(url).hostname == 'events.phuse.global' else ''


def discover(doc, url):
    found = {}
    # PHUSE's visible header cards carry their own event date, title and official link.
    for card in doc.select('.alert-bar_body__main-slide'):
        link = card.select_one('a[href]')
        title = card.select_one('.alert-bar_body_name-item')
        when = card.select_one('.alert-bar__date-of-event')
        target = event_url(link['href'], url) if link else ''
        if target and title and when:
            evidence = clean(when.get_text(' ', strip=True))
            found[target] = (clean(title.get_text(' ', strip=True)), event_day(evidence), evidence)
    # Calendar links use day + month heading + year heading, never the current year by inference.
    for block in doc.select('.calendar-block_box-item'):
        year = block.select_one('.calendar-block_box-item_headline')
        if not year or not re.fullmatch(r'20\d{2}', clean(year.get_text())):
            continue
        for month in block.select('.calendar-block_box'):
            heading = month.select_one('.calendar-block_box__headline')
            if not heading:
                continue
            for a in month.select('a.calendar-block_box-item__link[href]'):
                target = event_url(a['href'], url)
                label = clean(a.get_text(' ', strip=True))
                day = re.match(r'^(\d{1,2})(?:[–—-]\d{1,2})?:\s*(.+)', label)
                if target and day:
                    evidence = day[1] + ' ' + clean(heading.get_text()) + ' ' + clean(year.get_text())
                    found.setdefault(target, (day[2], event_day(evidence), evidence))
    if url == GROUPS:
        # Only event details from this official group, not footer/sponsor/registration links.
        for a in doc.select('a[href]'):
            target = event_url(a['href'], url)
            if target and '/event/WorkingGroupEvents/' in urlsplit(target).path and target != GROUPS:
                found.setdefault(target, ('', '', ''))
    return found


def read_event(url, title, index_day, index_evidence):
    doc = soup(url)
    content = body_text(doc)
    # Cvent's JSON-LD may describe the year-long umbrella event. Use the specific visible page.
    lines = []
    for node in doc.select('h1,h2,h3,p,time'):
        if node.find_parent(['nav', 'header', 'footer']):
            continue
        text = clean(node.get_text(' ', strip=True))
        if text and text not in lines:
            lines.append(text)
    evidence = next((line for line in lines[:40] if len(line) <= 240 and DATE_RE.search(line)), '')
    day = event_day(evidence) if evidence else index_day
    if not evidence:
        evidence = '官方活动目录日期: ' + index_evidence if index_day else ''
    if not title:
        date_pos = lines.index(evidence) if evidence in lines else 0
        candidates = [line for line in lines[:date_pos] if 20 <= len(line) <= 250 and 'sponsor' not in line.lower()]
        title = candidates[-1] if candidates else clean(doc.title.get_text() if doc.title else '')
    if not day or not title:
        raise ValueError('event page has no verifiable event date or title')
    return candidate('PHUSE', url, title, text=content, deadline=day,
                     deadline_evidence=evidence, basis='official-event-page')


def collect_events(start, today):
    result = Result()
    discovered = {}
    for url in (HOME, CALENDAR, GROUPS):
        try:
            entries = discover(soup(url), url)
            if not entries:
                raise ValueError('no recognizable events in official index')
            result.pages += 1
            for target, value in entries.items():
                if target not in discovered or (not discovered[target][0] and value[0]):
                    discovered[target] = value
        except Exception as exc:
            result.errors.append('PHUSE 活动目录读取失败（' + safe_error(exc) + '）')
            result.limited = True
    result.discovered = len(discovered)
    pending = []
    for url, (title, day, evidence) in discovered.items():
        if day and day < today:
            result.note('PHUSE', url, title, '', 'event-date', '过去事项', deadline=day)
        else:
            pending.append((url, title, day, evidence))
    # Upcoming known dates first; undated detail pages still receive a bounded discovery pass.
    pending.sort(key=lambda x: (x[2] or '9999', x[0]))
    if len(pending) > MAX_EVENTS:
        result.limited = True
        for url, title, day, evidence in pending[MAX_EVENTS:]:
            result.note('PHUSE', url, title, '', 'capacity', '活动读取达到上限，下轮继续检查', deadline=day)
    def read(args):
        try:
            return read_event(*args), None
        except Exception as exc:
            return None, safe_error(exc)
    with ThreadPoolExecutor(max_workers=5) as pool:
        for args, (row, error) in zip(pending[:MAX_EVENTS], pool.map(read, pending[:MAX_EVENTS])):
            url, title, day, evidence = args
            if error:
                result.errors.append('PHUSE 活动正文读取失败（' + error + '）')
                result.limited = True
                result.note('PHUSE', url, title, '', 'fetch', error, deadline=day)
            elif row['deadline'] < today:
                result.note('PHUSE', url, row['originalTitle'], '', 'event-date', '过去事项', deadline=row['deadline'])
            else:
                result.rows.append(row)
    return result
