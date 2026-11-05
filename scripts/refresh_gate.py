"""Skip duplicate daily triggers only when both published collections succeeded after 08:00 CST."""
import json
import os
from datetime import datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

CST = ZoneInfo("Asia/Shanghai")
STATUS_URL = "https://allensrj.github.io/biometrics-desk/refresh-status.json"


def already_refreshed(status, now):
    """Fail open: invalid/stale/failed state must never suppress a new collection."""
    if not isinstance(status, dict) or now.tzinfo is None:
        return False
    now = now.astimezone(CST)
    cutoff = now.replace(hour=8, minute=0, second=0, microsecond=0)
    for source in ("clinical", "github"):
        item = status.get(source)
        if not isinstance(item, dict) or item.get("ok") is not True:
            return False
        try:
            checked = datetime.fromisoformat(item["checked"].replace("Z", "+00:00"))
            if checked.tzinfo is None or not cutoff <= checked.astimezone(CST) <= now:
                return False
        except (KeyError, TypeError, ValueError, AttributeError):
            return False
    return True


def decide(daily, fetch_status, now):
    if not daily:
        return True, "手动运行：按请求执行，不做每日去重。"
    try:
        if already_refreshed(fetch_status(), now):
            return False, "线上两个模块均已在今天北京时间 08:00 后成功采集并发布，本次重复触发跳过。"
        return True, "线上尚无今天北京时间 08:00 后两个模块均成功的版本，执行刷新。"
    except Exception as exc:
        # Exception messages can contain request details. Record only the type.
        return True, f"线上状态读取失败（{type(exc).__name__}），为避免漏更新，继续刷新。"


def fetch_status():
    # Cache-busting matters when a retry follows a recent Pages deployment.
    request = Request(STATUS_URL + "?daily-check=" + os.environ.get("GITHUB_RUN_ID", "manual"),
                      headers={"User-Agent": "BiometricsDesk-Scheduler/1.0", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def main():
    daily = os.environ.get("DAILY_REFRESH") == "true"
    proceed, reason = decide(daily, fetch_status, datetime.now(CST))
    print(reason)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"proceed={str(proceed).lower()}\n")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write(f"## 每日刷新检查\n\n{reason}\n")


if __name__ == "__main__":
    main()
