"""Read versioned documents from maintained regulatory and terminology indexes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html import unescape
import re
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

PMDA = "https://www.pmda.go.jp/english/review-services/reviews/0002.html"
EMA = "https://www.ema.europa.eu/en/about-us/how-we-work/data-regulation-big-data-other-sources/use-clinical-study-data-medicine-evaluation"
NCI = "https://evs.nci.nih.gov/ftp1/CDISC/"


def read(url, limit=2_000_000):
    with urlopen(
        Request(url, headers={"User-Agent": "ClinicalRadar/1.0"}), timeout=25
    ) as response:
        return response.read(limit).decode("utf-8", errors="replace")


def pmda():
    page = (
        read(PMDA)
        .split('id="Standards"', 1)[1]
        .split("CDISC Data Validation Software", 1)[0]
    )
    catalog = re.search(r'href="([^"]+)">Data Standards Catalog \(([^)]+)\)', page)
    versions = re.findall(r'href="([^"]+)">Version ([\d.]+) \(([\d-]+)\)', page)
    path, version, date = max(versions, key=lambda v: v[2])
    return [
        dict(
            title=f"PMDA 日本电子研究数据标准目录（{catalog[2]}）",
            url=urljoin(PMDA, catalog[1]),
            published=catalog[2],
            summary="PMDA 的电子申报页面提供本版数据标准目录及可下载文件。",
            impact="在日本递交的研究中，对照目录核对数据集与配套标准的版本。",
        ),
        dict(
            title=f"PMDA 研究数据验证规则 v{version}",
            url=urljoin(PMDA, path),
            published=date,
            summary=f"日本电子研究数据申报页面列出的最新规则包为 v{version}，文件日期为 {date}。",
            impact="按申请日期核对规则的适用窗口，再确定 SDTM 和 ADaM 的验证配置。",
        ),
    ]


def nci():
    rows = []
    for model in ("SDTM", "ADaM"):
        url = f"{NCI}{model}/{model}%20Terminology.html"
        page = read(url, 16000)
        date = re.search(r"Controlled Terminology,\s*(\d{4}-\d\d-\d\d)", page)[1]
        rows.append(
            dict(
                title=f"NCI EVS：{model} 受控术语 {date} 版",
                url=url,
                published=date,
                summary=f"NCI EVS 的 {model} 发布文件列出了 {date} 版术语及 codelist。",
                impact="将项目锁定的 CT 版本与该发布文件对照，核查实际使用的代码值后再决定是否升级。",
            )
        )
    return rows


EMA_TITLES = {
    "Information about the clinical study data proof-of-concept pilot for industry": "面向申请人的试点说明",
    "Questions and answers about the clinical study data proof-of-concept pilot for industry": "申请人问答",
    "Data submission cover letter template": "数据递交附函模板",
    "Proof-of-concept pilot on using data from clinical studies in medicines evaluation: Interim report": "药品审评中使用临床研究数据的中期报告",
}


def ema():
    rows = []
    for block in read(EMA).split('class="mt-4 ema-file-wrapper"')[1:]:
        title = re.search(r'<p class="file-title [^>]+>(.*?)</p>', block, re.S)
        link = re.search(r'href="(/en/documents/[^"]+\.pdf)"', block)
        dates = re.findall(r'<time datetime="([\d-]{10})', block.split(">View<")[0])
        if not (title and link and dates):
            continue
        name = unescape(title[1]).strip()
        if not any(
            term in name.lower()
            for term in ("for industry", "interim report", "cover letter template")
        ):
            continue
        rows.append(
            dict(
                title="EMA 临床研究数据试点｜" + EMA_TITLES.get(name, name),
                url=urljoin(EMA, link[1]),
                published=max(dates),
                summary=f"官方文件《{name}》，资料页所列文件日期为 {max(dates)}。",
                impact="涉及欧盟试点的团队可按原文核对准备工作；适用范围限于相应试点。",
            )
        )
    if not rows:
        raise ValueError("未识别到试点文件")
    return rows


def collect(previous):
    statuses = []
    rows = []
    specs = [
        ("PMDA", PMDA, pmda, "国际监管", ["日本", "电子递交"]),
        ("NCI EVS", NCI, nci, "CDISC与标准", ["CDISC", "受控术语"]),
        ("EMA", EMA, ema, "国际监管", ["欧盟", "临床数据试点"]),
    ]
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(spec[2]) for spec in specs]
        for (name, url, _, category, tags), job in zip(specs, jobs):
            old = [x for x in previous if x.get("directSource") == name]
            known = {(x["url"], x["published"]): x["collected"] for x in old}
            error = ""
            try:
                records = job.result()
                for x in records:
                    x.update(
                        directSource=name,
                        source=name,
                        category=category,
                        importance="中",
                        tags=tags,
                        collected=known.get(
                            (x["url"], x["published"]), now.date().isoformat()
                        ),
                    )
            except Exception as exc:
                records = old
                error = (
                    f"HTTP {exc.code}"
                    if hasattr(exc, "code")
                    else f"读取或解析失败（{type(exc).__name__}）"
                )
            rows.extend(records)
            statuses.append(
                dict(
                    name=name,
                    url=url,
                    checked=now.isoformat(),
                    count=len(records),
                    error=error,
                )
            )
    return rows, statuses
