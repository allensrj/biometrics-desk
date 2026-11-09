"""Independent official-source discovery. Never consumes third-party radar data.

Adapters return official publication evidence separately from event dates.
Network/parse failures are reported; they are never interpreted as zero news.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import re
import time
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

TZ = ZoneInfo('Asia/Shanghai')
USER_AGENT = 'Mozilla/5.0 (compatible; BiometricsDesk/2.0; +https://github.com/allensrj/biometrics-desk)'
MONTHS = '|'.join('January February March April May June July August September October November December'.split())
DATE_RE = re.compile(r'\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b|20\d{2}年\s*\d{1,2}月\s*\d{1,2}日|\b20\d{6}\b|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:'+MONTHS+r')\s+20\d{2}\b|\b(?:'+MONTHS+r')\s+\d{1,2}(?:st|nd|rd|th)?,?\s+20\d{2}\b|\b20\d{2}\s+(?:'+MONTHS+r')\s+\d{1,2}(?:st|nd|rd|th)?\b', re.I)
KEYWORDS = re.compile(r'\b(?:CDISC|SDTM|ADaM|CDASH|SEND|define.xml|dataset.json|USDM|MedDRA|estimand|biostatistic\w*|statistic\w*|clinical|trial\w*|real.world|programming|submission|data standard\w*|data integrit\w*|data quality|terminology|ICH E\d|ICH M\d|patient.reported|endpoint\w*|analysis|analyses)\b|临床|统计|数据|生物等效|真实世界|试验设计|ICH', re.I)
EXCLUDE = re.compile(r'招聘|拟聘|资格审查|落户|党建|党风|采购|关爱计划|\b(?:job vacancy|career opportunity|fundraising)\b', re.I)
CATEGORIES = ('CDISC与标准', '中国监管', '国际监管', '统计方法', '行业与会议', '技术与工具')


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def parse_date(value):
    """Only complete dates; never invent a day for a month-only publication."""
    s = clean(value)
    if not s:
        return ''
    if re.match(r'^20\d\d-\d\d-\d\dT', s):
        try:
            stamp = datetime.fromisoformat(s.replace('Z', '+00:00'))
            return (stamp.astimezone(TZ).date() if stamp.tzinfo else stamp.date()).isoformat()
        except ValueError:
            return ''
    m = DATE_RE.search(s)
    if not m:
        return ''
    s = re.sub(r'(\d)(st|nd|rd|th)\b', r'\1', m[0], flags=re.I).replace(',', '')
    for fmt in ('%Y-%m-%d','%Y/%m/%d','%Y.%m.%d','%Y年%m月%d日','%Y%m%d','%d %B %Y','%B %d %Y','%Y %B %d'):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return ''


def get(url, json_body=False):
    for attempt in range(2):
        try:
            req = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json' if json_body else 'text/html,*/*'})
            with urlopen(req, timeout=35) as r:
                raw = r.read(16_000_001)
                if len(raw) > 16_000_000:
                    raise ValueError('response exceeds size limit')
                text = raw.decode(r.headers.get_content_charset() or 'utf-8', 'replace')
            return json.loads(text) if json_body else text
        except Exception:
            if attempt:
                raise
            time.sleep(1)


def soup(url):
    doc = BeautifulSoup(get(url), 'html.parser')
    if len(doc.get_text(strip=True)) < 120:
        raise ValueError('empty page or JavaScript challenge')
    return doc


def body_text(doc):
    root = doc.select_one('main, article, #main-content, .main-content') or doc.body or doc
    root = BeautifulSoup(str(root), 'html.parser')
    for x in root.select('script,style,nav,header,footer,form,.breadcrumb,.breadcrumbs'):
        x.decompose()
    return clean(root.get_text(' ', strip=True))


def relevant(title, text='', specialist=False):
    return not EXCLUDE.search(title) and (specialist or bool(KEYWORDS.search(title + ' ' + text)))


def candidate(name, url, title, published='', evidence='', text='', deadline='', deadline_evidence='', basis='official-page'):
    return dict(source=name, url=url, originalTitle=clean(title), published=parse_date(published),
                dateEvidence=clean(evidence), content=clean(text)[:14000], deadline=parse_date(deadline),
                deadlineEvidence=clean(deadline_evidence), contentBasis=basis)


def page_dates(doc):
    # Publication-specific metadata precedes visible publication labels. Never HTTP Last-Modified.
    for sel, attr in [('meta[property="article:published_time"]','content'), ('meta[name="DC.date.issued"]','content'), ('meta[name="dcterms.date"]','content'), ('time[itemprop="datePublished"]','datetime')]:
        node = doc.select_one(sel)
        if node and parse_date(node.get(attr)):
            return parse_date(node[attr]), sel + ': ' + node[attr]
    for block in doc.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(block.string or block.get_text())
            nodes = payload if isinstance(payload, list) else [payload]
            for n in nodes:
                if not isinstance(n,dict):
                    continue
                for item in [n] + n.get('@graph', []):
                    if isinstance(item,dict) and parse_date(item.get('datePublished')):
                        return parse_date(item['datePublished']), 'datePublished: ' + item['datePublished']
        except (ValueError,TypeError):
            pass
    text = body_text(doc)
    # No arbitrary "first date on page": it may be an event or footer copyright date.
    m = re.search(r'(?:Published Date|Date Published|Date of publication|发布时间|发布日期|发文日期)\s*[:：]?\s*(' + DATE_RE.pattern + ')', text, re.I)
    return (parse_date(m[1]), m[0]) if m else ('','')


def deadline_from(doc):
    text = body_text(doc)
    us=re.search(r'(?:Submit Comments by|Comment Closing Date)\s*[:：]?\s*(\d{1,2}/\d{1,2}/20\d{2})',text,re.I)
    if us:
        return us_date(us[1]),us[0]
    for pattern in [r'Comments Due By\s*[:：]?\s*', r'(?:comments? (?:must be received|due|by)|deadline|截止日期|截止时间)\s*(?:on|by|is|为|至|:|：)?\s*']:
        m = re.search(pattern + '(' + DATE_RE.pattern + ')', text, re.I)
        if m:
            return parse_date(m[1]), m[0]
    return '', ''


def nearby_date(anchor):
    # A list row is evidence for that anchor; do not walk to the whole list/page.
    parent = anchor
    for _ in range(4):
        parent = parent.parent
        if parent is None:
            break
        text = clean(parent.get_text(' ', strip=True))
        if len(text) > 1800:
            break
        dates = DATE_RE.findall(text)
        if dates:
            return parse_date(dates[0]), dates[0]
    return '', ''


def detail(name, url, title, published='', evidence='', specialist=False):
    doc = soup(url)
    content = body_text(doc)
    if name == 'PHUSE' and title in content:
        content = content[content.index(title):]
    if not relevant(title, content, specialist):
        return None
    official_date, official_evidence = page_dates(doc)
    deadline, deadline_evidence = deadline_from(doc)
    return candidate(name, url, title, official_date or published, official_evidence or evidence,
                     content, deadline, deadline_evidence)


class Result:
    def __init__(self):
        self.rows = []
        self.errors = []
        self.discovered = 0
        self.pages = 0
        self.undated = 0
        self.limited = False
        self.screening = []

    def note(self, source, url, title, published, stage, reason, **extra):
        self.screening.append(dict(source=source, url=url, title=clean(title), published=published,
                                   stage=stage, reason=reason, **extra))

    def fetch_detail(self, *args, **kwargs):
        try:
            row = detail(*args, **kwargs)
            if row:
                self.rows.append(row)
            else:
                self.note(args[0], args[1], args[2], args[3] if len(args)>3 else '', 'relevance', '正文初筛未命中领域词')
        except Exception as exc:
            self.errors.append(safe_error(exc))
            self.limited = True
            self.note(args[0], args[1], args[2], args[3] if len(args)>3 else '', 'fetch', safe_error(exc))


def safe_error(exc):
    return 'HTTP ' + str(exc.code) if hasattr(exc,'code') else type(exc).__name__


def cdisc_event_date(text):
    day=parse_date(text)
    clock=re.search(r'\b(\d{1,2}:\d{2})\s*(am|pm)\b',text,re.I)
    zone=re.search(r'\b(EST|EDT)\b',text)
    if day and clock and zone:
        local=datetime.strptime(day+' '+clock[1]+clock[2].upper(),'%Y-%m-%d %I:%M%p')
        return local.replace(tzinfo=ZoneInfo('America/New_York')).astimezone(TZ).date().isoformat()
    return day


def cdisc(start, today):
    result = Result()
    seen = set()
    indexes = ['https://www.cdisc.org/news', 'https://www.cdisc.org/news/whats-new',
               'https://www.cdisc.org/public-review', 'https://www.cdisc.org/events/webinars/upcoming']
    for base in indexes:
        url = base
        for page in range(5):
            try:
                doc = soup(url)
            except Exception as exc:
                result.errors.append('目录读取失败（'+safe_error(exc)+'）')
                break
            result.pages += 1
            root = doc.select_one('main') or doc
            links = []
            dates = []
            for a in root.select('a[href]'):
                target = urljoin(url,a['href']).split('#')[0]
                title = clean(a.get_text(' ',strip=True))
                if urlsplit(target).hostname != 'www.cdisc.org' or target in seen or len(title)<12:
                    continue
                if not any(x in urlsplit(target).path for x in ['/news/','/public-review/','/standards/','/events/webinar/']):
                    continue
                if target in indexes:
                    continue
                seen.add(target)
                published, evidence = nearby_date(a) if base.endswith("/news") else ("", "")
                dates.append(published)
                if published and published < start and '/news' in base:
                    result.note('CDISC', target, title, published, 'publication-date', f'发布日 {published} 早于近 90 天窗口（{start} 起），未读取正文')
                    continue
                links.append((target,title,published,evidence))
            result.discovered += len(links)
            for card in root.select('.card') if base.endswith('/webinars/upcoming') else []:
                a=card.select_one('a[href*="/events/webinar/"]')
                when=card.select_one('.daterange__date')
                if a and when:
                    event_text=clean(when.get_text(' ',strip=True))
                    result.rows.append(candidate('CDISC',urljoin(url,a['href']),a.get_text(' ',strip=True),
                                       text=card.get_text(' ',strip=True),deadline=cdisc_event_date(event_text),
                                       deadline_evidence=event_text,basis='official-event-index'))
            for target,title,published,evidence in links:
                if '/events/webinar/' in target:
                    continue
                result.fetch_detail('CDISC',target,title,published,evidence,specialist=True)
            nxt = root.select_one('a[rel="next"], .pager__item--next a')
            if not nxt or (dates and all(d and d < start for d in dates)):
                break
            url = urljoin(url,nxt['href'])
        else:
            result.limited = True
    if not result.discovered:
        raise ValueError('CDISC indexes returned no recognizable article links')
    return result


def post_json(url,payload):
    req=Request(url,data=json.dumps(payload).encode(),headers={'User-Agent':USER_AGENT,'Content-Type':'application/json'})
    with urlopen(req,timeout=40) as response:
        return json.load(response)


def phuse_blog(start,today):
    # PHUSE's HTML ignores page=N on server rendering. Use the very same public
    # GraphQL request its Next Page button makes, then read the official article.
    result=Result()
    query='''query getblogPosts($filter: BlogPostFiltersInput, $pagination: PaginationArg) {
      blogPosts(sort: "date_published:DESC", pagination: $pagination, filters: $filter) {
        data { id attributes { title category discription slug date_published } }
        meta { pagination { pageCount page pageSize total } }
      }
    }'''
    for page in range(1,11):
        payload={'query':query,'operationName':'getblogPosts',
                 'variables':{'filter':{'date_published':{'lte':today},'published':{'eq':True}},
                              'pagination':{'page':page,'pageSize':50}}}
        try:
            data=post_json('https://cms.phuse.global/graphql',payload)
            if data.get('errors'):
                raise ValueError('PHUSE official CMS rejected request')
            posts=data['data']['blogPosts']
            items=posts['data']
            pagination=posts['meta']['pagination']
            if not isinstance(items,list) or pagination['page']!=page:
                raise ValueError('PHUSE pagination schema changed')
        except Exception as exc:
            if not result.pages:
                raise
            result.errors.append('后续分页读取失败（'+safe_error(exc)+'）')
            break
        result.pages+=1
        dates=[]
        for item in items:
            row=item['attributes']
            result.discovered+=1
            published=parse_date(row['date_published'])
            dates.append(published)
            target='https://phuse.global/Communications/PHUSE_Blog/'+row['slug']
            if published and published<start:
                result.note('PHUSE', target, row['title'], published, 'publication-date', f'博客发布日 {published} 早于近 90 天窗口（{start} 起）')
                continue
            result.fetch_detail('PHUSE',target,row['title'],published,
                                'PHUSE 官方 CMS date_published: '+row['date_published'],specialist=True)
        if page>=pagination['pageCount'] or any(d and d<start for d in dates):
            break
    else:
        result.limited=True
    return result


def phuse(start,today):
    from phuse_events import collect_events
    combined = Result()
    for label, collect_part in (('PHUSE Blog', phuse_blog), ('PHUSE Events', collect_events)):
        try:
            part = collect_part(start,today)
            combined.rows.extend(part.rows)
            combined.screening.extend(part.screening)
            combined.errors.extend(part.errors)
            combined.pages += part.pages
            combined.discovered += part.discovered
            combined.limited = combined.limited or part.limited
        except Exception as exc:
            combined.errors.append(label + ': ' + safe_error(exc))
            combined.limited = True
    if not combined.pages:
        raise ValueError('PHUSE blog and event indexes unavailable')
    return combined


def federalregister(start,today):
    result=Result()
    query={'conditions[agencies][]':'food-and-drug-administration','conditions[publication_date][gte]':start,
           'conditions[publication_date][lte]':today,'per_page':100,'order':'newest'}
    url='https://www.federalregister.gov/api/v1/documents.json?'+urlencode(query)
    for page in range(10):
        data=get(url,True)
        if not isinstance(data.get('results'),list):
            raise ValueError('Federal Register response schema changed')
        result.pages+=1
        for item in data['results']:
            result.discovered+=1
            title=item['title']
            abstract=item.get('abstract') or ''
            if not relevant(title,abstract):
                excluded=EXCLUDE.search(title)
                if excluded:
                    reason='标题命中排除词：'+excluded[0]
                else:
                    reason='标题和官方摘要没有数据标准、试验设计、统计或递交等相关领域词，未送模型判断'
                result.note('美国联邦公报', item['html_url'], title, item['publication_date'], 'relevance', reason)
                continue
            # The official API abstract is explicitly labelled; no claim to have read a full PDF.
            result.rows.append(candidate('美国联邦公报',item['html_url'],title,item['publication_date'],
                               'publication_date: '+item['publication_date'],abstract,basis='official-api-abstract'))
        url=data.get('next_page_url')
        if not url:
            break
    else:
        result.limited=True
    return result


def versioned(name,fn):
    result=Result()
    result.rows=[]
    for item in fn():
        result.rows.append(candidate(name,item['url'],item['title'],item['published'],
                           '官方资料索引的版本/文件日期: '+item['published'],item['summary'],basis='official-version-index'))
    result.discovered=len(result.rows)
    result.pages=1
    return result


def ich(start,today):
    result=Result()
    def widget_text(node):
        if isinstance(node,list):
            return ' '.join(widget_text(x) for x in node)
        if isinstance(node,dict):
            return ' '.join(BeautifulSoup(v,'html.parser').get_text(' ',strip=True) if k=='text' and isinstance(v,str)
                            else widget_text(v) for k,v in node.items() if k not in ('actions','entityInfo','bundleInfo'))
        return ''
    for offset in range(0,500,50):
        url='https://admin.ich.org/api/v1/nodes?'+urlencode({'loadEntities[]':'paragraph','bundle':'news','limit':50,'offset':offset,'sort':'date:DESC,created:desc'})
        data=get(url,True)
        items=data.get('items')
        if not isinstance(items,list) or (offset==0 and not items):
            raise ValueError('ICH news schema changed')
        result.pages+=1
        dates=[]
        for item in items:
            info=item['bundleInfo']
            if not info.get('published'):
                continue
            published=parse_date(item.get('date'))
            dates.append(published)
            result.discovered+=1
            link=urljoin('https://www.ich.org/',info['alias'])
            if published and published<start:
                result.note('ICH', link, info['title'], published, 'publication-date', f'发布日 {published} 早于近 90 天窗口（{start} 起）')
                continue
            content=clean(item.get('summary','')+' '+widget_text(item.get('mainWidgets',{})))
            excluded=EXCLUDE.search(info['title'])
            if excluded:
                result.note('ICH', link, info['title'], published, 'relevance', '标题命中排除词: '+excluded[0])
                continue
            if not KEYWORDS.search(info['title']+' '+content):
                result.note('ICH', link, info['title'], published, 'relevance', '标题和正文没有临床统计编程相关领域词，未送模型判断')
                continue
            result.rows.append(candidate('ICH',link,info['title'],
                               published,'官网新闻 date: '+str(item.get('date','')),content,basis='official-cms-article'))
        if len(items)<50 or (dates and all(d and d<start for d in dates)):
            break
    else:
        result.limited=True
    return result


def cde(start,today):
    result=Result()
    base='https://www.cde.org.cn/'
    urls=[base,'https://www.cde.org.cn/main/news/listpage/3cc45b396497b598341ce3af000490e5']
    seen=set()
    for url in urls:
        try:
            doc=soup(url)
            result.pages+=1
        except Exception as exc:
            result.errors.append('栏目读取受限（'+safe_error(exc)+'）')
            result.limited=True
            continue
        for a in doc.select('a[href]'):
            target=urljoin(base,a['href'])
            title=clean(a.get_text(' ',strip=True))
            if '/main/news/viewInfoCommon/' not in target or target in seen:
                continue
            seen.add(target)
            result.discovered+=1
            published,evidence=nearby_date(a)
            if published and published<start:
                result.note('CDE', target, title, published, 'publication-date', f'发布日 {published} 早于近 90 天窗口（{start} 起）')
                continue
            if EXCLUDE.search(title):
                result.note('CDE', target, title, published, 'relevance', '命中明确排除词: ' + EXCLUDE.search(title)[0])
                continue
            try:
                row=detail('CDE',target,title,published,evidence,specialist=True)
                if row:
                    result.rows.append(row)
            except Exception as exc:
                # A real official index notice remains usable, but cannot stand in for a full guideline.
                result.errors.append('正文读取受限（'+safe_error(exc)+'），部分条目仅依据官网公告目录')
                result.limited = True
                result.note('CDE', target, title, published, 'fetch', '正文读取失败，仅可使用明确标注的官方目录事实: ' + safe_error(exc))
                if published:
                    result.rows.append(candidate('CDE',target,title,published,'官网公告目录: '+evidence,
                                       '官方公告标题：'+title+'。目录发布日期：'+published+'。正文未能读取，不推断指南具体要求。',basis='official-index-only'))
    if not result.pages or not result.discovered:
        raise ValueError('CDE returned no recognizable notices')
    # The homepage is a rolling subset; a blocked archive is not a complete 90-day backfill.
    return result


def us_date(value):
    try:
        return datetime.strptime(clean(value),'%m/%d/%Y').date().isoformat()
    except ValueError:
        return parse_date(value)


def fda(start,today):
    result=Result()
    url='https://www.fda.gov/drugs/guidances-drugs/newly-added-guidance-documents'
    doc=soup(url)
    result.pages+=1
    found=0
    for tr in doc.select('table tr'):
        cells=tr.find_all('td')
        if len(cells)<4:
            continue
        a=cells[1].find('a',href=True)
        if not a:
            continue
        found+=1
        published=us_date(cells[-1].get_text(' ',strip=True))
        title=clean(a.get_text(' ',strip=True))
        target=urljoin(url,a['href'])
        result.discovered+=1
        if not published:
            result.note('FDA', target, title, '', 'publication-date', '目录没有可靠的发布日期，未当作新闻')
            continue
        if published<start:
            result.note('FDA', target, title, published, 'publication-date', f'发布日 {published} 早于近 90 天窗口（{start} 起）')
            continue
        if published>today:
            result.note('FDA', target, title, published, 'publication-date', f'发布日 {published} 晚于采集日 {today}')
            continue
        evidence='FDA guidance Issue Date: '+cells[-1].get_text(' ',strip=True)
        try:
            row=detail('FDA',target,title,published,evidence,specialist=True)
            if row:
                # FDA issue date is document-specific; generic page maintenance is not a new issue.
                row['published']=published
                row['dateEvidence']=evidence
                result.rows.append(row)
        except Exception as exc:
            result.errors.append('部分正文读取失败（'+safe_error(exc)+'）')
            result.rows.append(candidate('FDA',target,title,published,evidence,
                               'Official guidance index: '+clean(tr.get_text(' ',strip=True)),basis='official-index-only'))
    if not found:
        raise ValueError('FDA guidance table schema changed')
    return result


def specifications():
    from official_sources import pmda,nci,ema,PMDA,NCI,EMA
    return [
        ('CDISC','https://www.cdisc.org/news/whats-new','新闻、最新标准、公开征求意见、近期网络研讨会',cdisc),
        ('CDE','https://www.cde.org.cn/','官网首页公告及工作动态目录；目录受限时标注覆盖不完整',cde),
        ('ICH','https://www.ich.org/','官网新闻 CMS：按 date 字段分页，读取文章正文',ich),
        ('FDA','https://www.fda.gov/drugs/guidances-drugs/newly-added-guidance-documents','新发布药品指南目录与原文',fda),
        ('PHUSE','https://phuse.global/','官方 Blog、活动日历、工作组活动页与首页活动入口',phuse),
        ('美国联邦公报','https://www.federalregister.gov/agencies/food-and-drug-administration','FDA 正式公告 API：90 天分页、读取官方摘要',federalregister),
        ('PMDA',PMDA,'电子研究数据标准目录与最新验证规则',lambda s,t:versioned('PMDA',pmda)),
        ('NCI EVS',NCI,'SDTM、ADaM 受控术语最新版本',lambda s,t:versioned('NCI EVS',nci)),
        ('EMA',EMA,'临床研究数据试点资料索引',lambda s,t:versioned('EMA',ema)),
    ]
