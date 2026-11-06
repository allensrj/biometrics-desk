import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'collector'))
from bs4 import BeautifulSoup
from clinical_sources import parse_date,page_dates,deadline_from,candidate,Result,ich,federalregister,nearby_date,phuse_blog as phuse,cdisc_event_date
from clinical_pipeline import eligible,independent_previous,collect,VERSION
from clinical_analysis import validate

class Dates(unittest.TestCase):
    def test_timezone_and_explicit_dates(self):
        self.assertEqual(parse_date('2026-11-03T18:00:00Z'),'2026-11-04')
        self.assertEqual(parse_date('2026 October 22nd'),'2026-10-22')
        self.assertEqual(parse_date('20261023'),'2026-10-23')
        self.assertEqual(parse_date('25 September 2026'),'2026-09-25')
        self.assertEqual(parse_date('October 2026'),'')
    def test_event_and_footer_cannot_be_publication(self):
        doc=BeautifulSoup('<main><h1>Review</h1>Comments Due By 20 November 2026</main><footer>Updated 4 November 2026</footer>','html.parser')
        self.assertEqual(page_dates(doc),('',''))
        self.assertEqual(deadline_from(doc)[0],'2026-11-20')
    def test_labeled_publication(self):
        doc=BeautifulSoup('<main>Published Date : 25 September 2026</main>','html.parser')
        self.assertEqual(page_dates(doc)[0],'2026-09-25')
    def test_fda_comment_deadline_and_event_timezone(self):
        doc=BeautifulSoup('<main>Submit Comments by 12/01/2026</main>','html.parser')
        self.assertEqual(deadline_from(doc)[0],'2026-12-01')
        self.assertEqual(page_dates(doc),('',''))
        self.assertEqual(cdisc_event_date('17 November 2026 11:30am - 1:00pm EST'),'2026-11-18')
    def test_exact_90_inclusive_days(self):
        start='2026-08-07'; end='2026-11-04'
        self.assertEqual(eligible({'published':start},start,end),'news')
        self.assertEqual(eligible({'published':'2026-08-06'},start,end),'')
        self.assertEqual(eligible({'published':'2026-11-05'},start,end),'')
        self.assertEqual(eligible({'published':'2025-03-14','deadline':'2026-11-20','deadlineEvidence':'Comments Due By 20 November 2026'},start,end),'agenda')
        self.assertEqual(eligible({'published':'','deadline':'2026-11-20'},start,end),'')
    def test_phuse_row_date(self):
        doc=BeautifulSoup('<div class="blog_post"><div>2026 October 22nd</div><div><a href="/article"><h4>Responsible clinical programming</h4></a></div></div>','html.parser')
        self.assertEqual(nearby_date(doc.a)[0],'2026-10-22')

class Independence(unittest.TestCase):
    def test_old_aggregates_never_retained(self):
        legacy={'source':'FDA','published':'2026-10-30'}
        direct={'source':'FDA','provenance':{'kind':VERSION}}
        self.assertEqual(independent_previous({'items':[legacy,direct]}),[direct])
    def test_failure_does_not_resurrect_legacy(self):
        def failure(*args): raise OSError('source unavailable')
        def good(*args): return Result()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'clinical.json').write_text(json.dumps({'items':[{'source':'FDA','published':'2026-10-30','url':'https://www.fda.gov/legacy'}]}))
            specs=[('FDA','https://www.fda.gov/','test',failure),('ICH','https://www.ich.org/','test',good)]
            with patch('clinical_pipeline.sources.specifications',return_value=specs),patch('clinical_pipeline.analyze',return_value=([],[],[])),patch('clinical_pipeline.write_summary'):
                result=collect(root,root,date(2026,11,4))
            self.assertEqual(result['items'],[])
            self.assertFalse(result['sources'][0]['ok'])
            self.assertTrue(result['sources'][1]['ok'])
            self.assertEqual(result['windowStart'],'2026-08-07')
    def test_unsupported_model_claim_not_published(self):
        row={'content':'Official clinical trial statistical analysis guidance.'}
        v={'relevant':True,'title':'指南','summary':'官方指南','impact':'阅读原文','category':'统计方法','importance':'高','tags':[],'evidence':'Completely invented requirement'}
        with self.assertRaises(ValueError): validate(v,row)
        v['evidence']='clinical trial statistical analysis'
        v['published']='2026-11-04';v['url']='https://attacker.invalid/'
        out=validate(v,row)
        self.assertNotIn('published',out)
        self.assertNotIn('url',out)
    def test_ich_reads_official_cms(self):
        payload={'items':[{'bundleInfo':{'published':True,'title':'Clinical trial data standards','alias':'/news/test'},'date':'2026-10-06T12:00:00+0200','summary':'Clinical trial data governance','mainWidgets':{'items':[{'text':'<p>New statistical guidance for clinical trial data.</p>'}]}}]}
        with patch('clinical_sources.get',return_value=payload) as fetch:
            rows=ich('2026-08-07','2026-11-04').rows
        self.assertTrue(fetch.call_args.args[0].startswith('https://admin.ich.org/'))
        self.assertEqual(rows[0]['published'],'2026-10-06')
        self.assertIn('New statistical guidance',rows[0]['content'])
    def test_phuse_uses_real_cms_pagination(self):
        def payload(page,day):
            return {'data':{'blogPosts':{'data':[{'attributes':{'title':'Clinical statistical programming','slug':f'article-{page}','date_published':day}}],
                    'meta':{'pagination':{'page':page,'pageCount':3,'total':3}}}}}
        with patch('clinical_sources.post_json',side_effect=[payload(1,'2026-10-22'),payload(2,'2026-08-13'),payload(3,'2026-08-05')]) as fetch,patch.object(Result,'fetch_detail') as detail:
            result=phuse('2026-08-07','2026-11-04')
        self.assertEqual(fetch.call_count,3)
        self.assertEqual(detail.call_count,2)
        self.assertFalse(result.limited)
        self.assertEqual(fetch.call_args_list[1].args[1]['variables']['pagination']['page'],2)
    def test_fr_paginates_official_results(self):
        def item(n): return {'title':'Statistical analysis in clinical trials','html_url':f'https://www.federalregister.gov/documents/{n}','publication_date':'2026-10-30','abstract':'Clinical trial design and statistical analysis.'}
        payloads=[{'results':[item(1)],'next_page_url':'https://www.federalregister.gov/api/v1/documents?page=2'},{'results':[item(2)]}]
        with patch('clinical_sources.get',side_effect=payloads) as fetch:
            result=federalregister('2026-08-07','2026-11-04')
        self.assertEqual(len(result.rows),2)
        self.assertEqual(fetch.call_count,2)

if __name__=='__main__': unittest.main()
