"""Refresh both dashboard sources, preserving the last good snapshot on failure."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PRIVATE = Path(os.environ.get("RADAR_STATE_DIR", Path.home() / "Library/Application Support/ClinicalRadar"))
sys.path.insert(0, str(ROOT / "collector"))
from automation import atomic_write_json, run
from clinical_pipeline import collect as collect_clinical
from release_watch import collect as collect_releases


def clinical():
    return collect_clinical(ROOT, PRIVATE)


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
            result = action()
            if key == "clinical":
                entry["degraded"] = any(not s["ok"] or s["limited"] or s["pendingAnalysis"] for s in result["sources"])
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
