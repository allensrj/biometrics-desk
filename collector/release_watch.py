"""Check official releases of recently active, domain-relevant public repositories."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
from automation import _http_json

CLINICAL = re.compile(
    r"clinical|pharma|biometr|biostat|cdisc|sdtm|(?-i:ADaM)|adamig|admiral|submission|define[\.\- ]xml|dataset[\.\-]json|patient.level|tl[fg]s?\b|gsdesign|metalite|gtsummary|riskmetric|safetygraphic|adverse.event",
    re.I,
)
# Entirely clinical-programming homes. Company orgs stay on the keyword filter above.
FOCUSED = {
    "pharmaverse",
    "cdisc-org",
    "phuse-org",
    "openpharma",
    "insightsengineering",
    "gsk-biostatistics",
    "pharmar",
    "safetygraphics",
}


def collect(accounts, token, start, previous):
    def api(path):
        return _http_json("https://api.github.com/" + path, token=token, timeout=15)

    def recent(account):
        releases = []
        page = 1
        while True:
            repos = api(
                f"users/{account}/repos?type=owner&sort=pushed&direction=desc&per_page=100&page={page}"
            )
            for repo in repos:
                if not repo.get("pushed_at") or repo["pushed_at"] < start:
                    return releases
                if repo["fork"] or repo["private"]:
                    continue
                text = " ".join(
                    [
                        repo["name"],
                        repo.get("description") or "",
                        *repo.get("topics", []),
                    ]
                )
                if account.lower() not in FOCUSED and not CLINICAL.search(text):
                    continue
                for item in api(f"repos/{repo['full_name']}/releases?per_page=10"):
                    if (
                        not item["prerelease"]
                        and not item["draft"]
                        and (item.get("published_at") or "") >= start
                    ):
                        releases.append(
                            dict(
                                repo=repo["full_name"],
                                tag=item["tag_name"],
                                url=item["html_url"],
                                date=item["published_at"],
                            )
                        )
            if len(repos) < 100:
                return releases
            page += 1

    start = (
        datetime.fromisoformat(start)
        .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        .astimezone(ZoneInfo("UTC"))
        .isoformat()
        .replace("+00:00", "Z")
    )
    rows, failures = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {a: pool.submit(recent, a) for a in accounts}
        for account, job in jobs.items():
            try:
                rows.extend(job.result())
            except Exception:
                failures.append(account)
                rows.extend(
                    r
                    for r in previous
                    if r["repo"].split("/")[0].lower() == account.lower()
                    and r["date"] >= start
                )
    return sorted(rows, key=lambda r: r["date"], reverse=True), failures
