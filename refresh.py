"""Refresh both dashboard sources, preserving the last good snapshot on failure."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PRIVATE = Path(os.environ.get("RADAR_STATE_DIR", Path.home() / "Library/Application Support/ClinicalRadar"))
sys.path.insert(0, str(ROOT / "collector"))
from automation import atomic_write_json, run
from official_sources import collect
from release_watch import collect as collect_releases


def upstream_clinical():
    from urllib.request import urlopen
    with urlopen("https://raw.githubusercontent.com/EmilyLiu312/clinical-biometrics-radar/main/data.json", timeout=60) as response:
        data = json.load(response)
    fields = ("title", "url", "category", "importance", "summary", "impact", "source")
    if (
        not isinstance(data.get("items"), list)
        or not data["items"]
        or not data.get("updated")
        or any(
            not isinstance(item, dict)
            or not all(isinstance(item.get(k), str) and item[k] for k in fields)
            or not isinstance(item.get("tags", []), list)
            for item in data["items"]
        )
    ):
        raise ValueError("临床源未提供有效快照")
    return data


def clinical():
    path = ROOT / "clinical.json"
    saved = json.loads(path.read_text()) if path.exists() else {}
    previous = saved.get("items", []) + saved.get("agendaOnly", [])
    try:
        data = upstream_clinical()
    except (OSError, ValueError, subprocess.SubprocessError):
        data = dict(saved)
        data["items"] = [item for item in previous if not item.get("directSource")]
        data["upstreamError"] = "汇总源本轮同步失败。"
    else:
        data["upstreamChecked"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    direct, data["directSources"] = collect(previous)
    select_news(data, direct + data["items"])
    atomic_write_json(str(path), data)


def select_news(data, candidates, today=None):
    today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    start = today - timedelta(days=89)
    news, agenda = [], []
    for item in candidates:
        try:
            published = date.fromisoformat(item.get("published") or "")
        except ValueError:
            published = None
        # Some upstream notices put a scheduled meeting date in the publication field.
        event_date = item.get("deadline") == item.get("published") and (
            item.get("collected") or "9999"
        ) < (item.get("published") or "")
        if published and start <= published <= today and not event_date:
            news.append(item)
        elif (item.get("deadline") or "") >= today.isoformat():
            agenda.append(item)
    data["items"] = sorted(news, key=lambda item: item["published"], reverse=True)
    data["agendaOnly"] = agenda
    data.pop("sourceChecks", None)


def repositories():
    creds = {"githubToken": os.environ.get("GITHUB_TOKEN"), "deepseekApiKey": os.environ.get("DEEPSEEK_API_KEY")}
    if not os.environ.get("GITHUB_TOKEN"):
        from shutil import which

        gh = which("gh") or "/usr/local/bin/gh"
        if Path(gh).exists():
            token = subprocess.run(
                [gh, "auth", "token", "--hostname", "github.com"],
                capture_output=True,
                text=True,
            )
            if token.returncode == 0:
                creds["githubToken"] = token.stdout.strip()
    local_secrets = PRIVATE / "secrets.json"
    if not creds["deepseekApiKey"] and local_secrets.exists():
        creds["deepseekApiKey"] = json.loads(local_secrets.read_text())[
            "deepseekApiKey"
        ]
    if not creds["githubToken"]:
        raise ValueError("缺少 GitHub 凭据")
    if not creds["deepseekApiKey"]:
        raise ValueError("缺少 DeepSeek 凭据")
    data = run({"input": creds, "workspacePath": str(PRIVATE)})["artifact"]
    if any(word in data.get("note", "") for word in ["失败", "损坏", "未抓取"]):
        raise RuntimeError("GitHub 采集失败")
    warnings = data.get("errors", "").split("；")
    data["errors"] = "；".join(
        dict.fromkeys(
            "DeepSeek 判读不可用，候选仓库暂列待确认" if "DeepSeek" in w else w.split(":")[0]
            for w in warnings
        )
    )
    refresh_releases(data, creds["githubToken"])
    atomic_write_json(str(ROOT / "repositories.json"), data)


def refresh_releases(data, token):
    path = ROOT / "repositories.json"
    previous = json.loads(path.read_text()).get("releases", []) if path.exists() else []
    data["releases"], data["releaseErrors"] = collect_releases(
        data["watchAccounts"], token, data["windowStart"], previous
    )


def main():
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = (PRIVATE / "refresh.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    path = ROOT / "refresh-status.json"
    status = json.loads(path.read_text()) if path.exists() else {}
    failed = False
    for key, action in [("clinical", clinical), ("github", repositories)]:
        entry = status.setdefault(key, {})
        try:
            action()
            entry.update(
                ok=True, checked=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
            )
        except Exception as exc:
            entry.update(ok=False)
            print(key, type(exc).__name__, file=sys.stderr)
            failed = True
        atomic_write_json(str(path), status)
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
