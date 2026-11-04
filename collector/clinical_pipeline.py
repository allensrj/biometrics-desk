"""Daily independent clinical collection, publication window and provenance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, date
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from automation import atomic_write_json
import clinical_sources as sources
from clinical_analysis import analyze

VERSION='official-direct-v1'
TZ=ZoneInfo('Asia/Shanghai')


def eligible(row,start,today):
    published=row.get('published','')
    if published and start <= published <= today:
        return 'news'
    deadline=row.get('deadline','')
    if deadline and today <= deadline and row.get('deadlineEvidence'):
        return 'agenda'
    return ''


def independent_previous(data):
    return [row for row in data.get('items',[])+data.get('agendaOnly',[])
            if row.get('provenance',{}).get('kind')==VERSION]


def collect(root,private,today=None):
    now=datetime.now(TZ)
    today=today or now.date()
    end=today.isoformat()
    start=(today-timedelta(days=89)).isoformat()
    path=Path(root)/'clinical.json'
    saved=json.loads(path.read_text()) if path.exists() else {}
    previous=independent_previous(saved)
    specs=sources.specifications()
    statuses=[]
    candidates=[]
    excluded={'outsideWindow':0,'unknownPublicationDate':0}
    successful=0
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs=[pool.submit(fn,start,end) for _,_,_,fn in specs]
        for (name,url,scope,_),job in zip(specs,jobs):
            status={'name':name,'url':url,'scope':scope,'checked':datetime.now(TZ).isoformat(),
                    'ok':False,'discovered':0,'read':0,'eligible':0,'unknownDate':0,'error':'','limited':False}
            try:
                result=job.result()
                successful+=1
                status.update(ok=not result.errors,discovered=result.discovered,read=len(result.rows),pages=result.pages,
                              limited=result.limited,error='；'.join(sorted(set(result.errors))))
                seen=set()
                for row in result.rows:
                    key=(row['url'],row['published'])
                    if key in seen:
                        continue
                    seen.add(key)
                    if eligible(row,start,end):
                        candidates.append(row)
                        status['eligible']+=1
                    elif not row['published']:
                        status['unknownDate']+=1
                        excluded['unknownPublicationDate']+=1
                    else:
                        excluded['outsideWindow']+=1
            except Exception as exc:
                status['error']=sources.safe_error(exc)
            status['checked']=datetime.now(TZ).isoformat()
            statuses.append(status)
            print(f"SOURCE {name}: discovered={status['discovered']} read={status['read']} eligible={status['eligible']} error={status['error'] or '-'}",flush=True)
    if not successful:
        raise RuntimeError('All official sources failed; keeping published snapshot')
    accepted,rejected,pending=analyze(candidates,private)
    rejected_urls={row['url'] for row in rejected}
    # No legacy aggregated rows survive this migration. Only our own verified history is reusable.
    merged={row['url']:row for row in previous if eligible(row,start,end) and row['url'] not in rejected_urls}
    old_by_url={row['url']:row for row in previous}
    for row in accepted:
        old=old_by_url.get(row['url'],{})
        row['collected']=old.get('collected') or now.isoformat()
        row['lastVerified']=now.isoformat()
        row['provenance']={'kind':VERSION,'url':row['url'],'dateEvidence':row['dateEvidence'],
                           'contentBasis':row['contentBasis']}
        merged[row['url']]=row
    news=[]
    agenda=[]
    for row in merged.values():
        if eligible(row,start,end)=='news':
            news.append(row)
        elif eligible(row,start,end)=='agenda':
            agenda.append(row)
    news.sort(key=lambda row:(row['published'],row['source'],row['url']),reverse=True)
    agenda.sort(key=lambda row:row['deadline'])
    for status in statuses:
        name=status['name']
        status['included']=sum(row['source']==name for row in news)
        status['agenda']=sum(row['source']==name for row in agenda)
        status['pendingAnalysis']=sum(row['source']==name for row in pending)
        dates=[row['published'] for row in news if row['source']==name]
        status['latestPublished']=max(dates,default='')
        status['retained']=sum(row['source']==name and row.get('lastVerified')!=now.isoformat() for row in news+agenda)
        if not status['ok'] and not status['error']:
            status['error']='读取未完成'
    data={'collectorVersion':VERSION,'updated':now.isoformat(),'windowStart':start,'windowEnd':end,
          'items':news,'agendaOnly':agenda,'sources':statuses,
          'analysis':{'method':'DeepSeek 独立分析官网正文、官方摘要或资料索引','accepted':len(accepted),
                      'irrelevant':len(rejected),'pending':len(pending)},'excluded':excluded}
    report={k:v for k,v in data.items() if k not in ('items','agendaOnly')}
    report.update(pending=pending,rejected=rejected,
                  records=[{k:row.get(k,'') for k in ('source','url','originalTitle','published','dateEvidence','deadline','deadlineEvidence','contentBasis','lastVerified')} for row in news+agenda])
    atomic_write_json(str(path),data)
    atomic_write_json(str(Path(root)/'collection-report.json'),report)
    write_summary(data)
    return data


def write_summary(data):
    lines=['## 临床情报：独立官网采集','',f"北京时间窗口：{data['windowStart']} 至 {data['windowEnd']}（含首尾）。",
           '', '| 来源 | 本轮读取 | 收录新闻 | 近期事项 | 最新发布日期 | 状态 |','| --- | ---: | ---: | ---: | --- | --- |']
    for s in data['sources']:
        notes=[]
        if s['error']: notes.append(s['error'])
        if s['limited']: notes.append('达到分页上限/范围受限')
        if s['unknownDate']: notes.append(f"{s['unknownDate']} 条缺少可靠发布日期")
        if s['pendingAnalysis']: notes.append(f"{s['pendingAnalysis']} 条待分析重试")
        if s['retained']: notes.append(f"沿用 {s['retained']} 条本项目历史记录")
        lines.append(f"| {s['name']} | {s['read']} | {s['included']} | {s['agenda']} | {s['latestPublished'] or '—'} | {'；'.join(notes) or '成功'} |")
    lines += ['', '第三方汇总不参与采集。没有可信日期的内容不会进入新闻列表；正文分析未通过的候选不冒充已完成情报。',
              f"\n新闻 {len(data['items'])} 条；近期事项专用 {len(data['agendaOnly'])} 条；分析待重试 {data['analysis']['pending']} 条。"]
    text='\n'.join(lines)+'\n'
    print(text,flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as fh:
            fh.write(text)
