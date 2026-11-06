from datetime import date
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'collector'))
from bs4 import BeautifulSoup
from phuse_events import discover, read_event, event_day, collect_events, HOME, CALENDAR, GROUPS
from clinical_sources import phuse, fda, cde, Result
from clinical_pipeline import collect


def html(text):
    return BeautifulSoup(text, 'html.parser')


class OfficialEvents(unittest.TestCase):
    def test_specific_visible_event_ignores_umbrella_schema_dates(self):
        doc = html('''<title>ASA Webinar</title><script type="application/ld+json">{"@type":"Event","startDate":"2026-01-01","datePublished":"2026-01-01"}</script>
        <p>Scientific Evaluation of Safety Data – Safety Estimands</p>
        <p>10 November 2026 11:00–12:30 (EST) / 16:00–17:30 (GMT)</p>
        <p>ICH E9(R1) safety estimands, AE incidence and competing risks.</p>''')
        with patch('phuse_events.soup', return_value=doc):
            row = read_event('https://events.phuse.global/event/WorkingGroupEvents/ASA-Webinar', '', '', '')
        self.assertEqual(row['published'], '')
        self.assertEqual(row['deadline'], '2026-11-11')
        self.assertIn('10 November', row['deadlineEvidence'])
        self.assertIn('Safety Estimands', row['originalTitle'])
        self.assertIn('competing risks', row['content'])

    def test_event_timezone_and_date_only(self):
        self.assertEqual(event_day('10 November 2026 11:00–12:30 (EST)'), '2026-11-11')
        self.assertEqual(event_day('10 November 2026 16:00–17:30 (GMT)'), '2026-11-11')
        self.assertEqual(event_day('15 November 2026'), '2026-11-15')
        self.assertEqual(event_day('15–18 November 2026'), '2026-11-15')
        self.assertEqual(event_day('November 2026'), '')

    def test_card_discovery_not_limited_to_blog_and_no_external_destinations(self):
        card = '''<div class="alert-bar_body__main-slide"><span class="alert-bar_body_name-item">Safety estimands</span><div class="alert-bar__date-of-event">10th November 2026</div><a href="https://events.phuse.global/event/WorkingGroupEvents/ASA-Webinar">Go</a></div>'''
        doc = html(card + card.replace('events.phuse.global', 'example.com'))
        rows = discover(doc, HOME)
        self.assertEqual(len(rows), 1)
        self.assertEqual(next(iter(rows.values()))[1], '2026-11-10')

    def test_calendar_requires_explicit_year(self):
        snippet = '''<div class="calendar-block_box-item"><h2 class="calendar-block_box-item_headline">2027</h2><div class="calendar-block_box"><h3 class="calendar-block_box__headline">January</h3><a class="calendar-block_box-item__link" href="https://events.phuse.global/APACConnect27">28–30: APAC Connect</a></div></div>'''
        self.assertEqual(next(iter(discover(html(snippet), CALENDAR).values()))[1], '2027-01-28')
        self.assertEqual(discover(html(snippet.replace('2027', '')), CALENDAR), {})

    def test_working_group_generic_registration_link_is_discovered(self):
        doc = html('<a href="/event/WorkingGroupEvents/ASA-Webinar">Register now</a><a href="https://www.eventbrite.com/register">Register</a>')
        self.assertIn('https://events.phuse.global/event/WorkingGroupEvents/ASA-Webinar', discover(doc, GROUPS))

    def test_index_and_detail_failures_recorded_not_zero_success(self):
        url = 'https://events.phuse.global/event/WorkingGroupEvents/test'
        with patch('phuse_events.soup', side_effect=[OSError('blocked'), html('<main>index</main>'), html('<main>index</main>')]), patch('phuse_events.discover', return_value={url: ('Test', '2026-11-10', '10 November 2026')}), patch('phuse_events.read_event', side_effect=OSError('blocked')):
            result = collect_events('2026-08-09', '2026-11-06')
        self.assertTrue(result.limited)
        self.assertTrue(result.errors)
        self.assertEqual(result.screening[0]['url'], url)
        self.assertEqual(result.screening[0]['stage'], 'fetch')

    def test_blog_failure_does_not_hide_successful_event_rows(self):
        events = Result(); events.pages = 1
        events.rows = [{'source': 'PHUSE', 'url': 'https://events.phuse.global/event/test'}]
        with patch('clinical_sources.phuse_blog', side_effect=OSError('blog unavailable')), patch('phuse_events.collect_events', return_value=events):
            result = phuse('2026-08-09', '2026-11-06')
        self.assertEqual(result.rows, events.rows)
        self.assertTrue(result.limited)

    def test_past_detail_not_promoted_to_new_news(self):
        url = 'https://events.phuse.global/event/WorkingGroupEvents/old'
        old = {'source': 'PHUSE', 'url': url, 'originalTitle': 'Past event', 'published': '', 'deadline': '2026-11-05'}
        with patch('phuse_events.soup', return_value=html('<main>Index</main>')), patch('phuse_events.discover', return_value={url: ('', '', '')}), patch('phuse_events.read_event', return_value=old):
            result = collect_events('2026-08-09', '2026-11-06')
        self.assertEqual(result.rows, [])
        self.assertEqual(result.screening[0]['reason'], '过去事项')


class ScreeningAudit(unittest.TestCase):
    def test_fda_recent_guidance_reaches_detail_without_keyword(self):
        doc = html('<table><tr><td>Generic Drugs</td><td><a href="/guidance">Evaluation of Therapeutic Equivalence</a></td><td>Final</td><td>08/24/2026</td></tr></table>')
        row = {'source': 'FDA', 'url': 'https://www.fda.gov/guidance', 'published': ''}
        with patch('clinical_sources.soup', return_value=doc), patch('clinical_sources.detail', return_value=row) as detail:
            result = fda('2026-08-09', '2026-11-06')
        self.assertTrue(detail.call_args.kwargs['specialist'])
        self.assertEqual(result.rows[0]['published'], '2026-08-24')

    def test_cde_keyword_free_technical_title_reaches_detail(self):
        doc = html('<main><div><a href="/main/news/viewInfoCommon/test">关于新生抗原药品关键问题的技术考虑</a><time>20261030</time></div></main>')
        row = {'source': 'CDE', 'published': '2026-10-30'}
        with patch('clinical_sources.soup', return_value=doc), patch('clinical_sources.detail', return_value=row) as detail:
            result = cde('2026-08-09', '2026-11-06')
        self.assertEqual(detail.call_count, 1)
        self.assertTrue(detail.call_args.kwargs['specialist'])
        self.assertEqual(len(result.rows), 1)

    def test_screening_and_discovered_dates_exported_separately(self):
        source = Result(); source.pages = 1; source.discovered = 1
        source.note('FDA', 'https://www.fda.gov/test', 'Not relevant', '2026-11-03', 'relevance', 'test exclusion')
        with tempfile.TemporaryDirectory() as tmp:
            specs = [('FDA', 'https://www.fda.gov/', 'test', lambda *_: source)]
            with patch('clinical_pipeline.sources.specifications', return_value=specs), patch('clinical_pipeline.analyze', return_value=([], [], [])), patch('clinical_pipeline.write_summary'):
                result = collect(Path(tmp), Path(tmp), date(2026, 11, 6))
            report = json.loads((Path(tmp)/'collection-report.json').read_text())
        self.assertEqual(report['screening'][0]['stage'], 'relevance')
        self.assertEqual(result['sources'][0]['latestDiscoveredPublished'], '2026-11-03')
        self.assertEqual(result['sources'][0]['latestIncludedPublished'], '')
