# -*- coding: utf-8 -*-
"""
药企开源仓库雷达 · 每日简报
GitHub Search API -> 两级关键词过滤 -> README 二次校验 -> 去重/7天回看 -> DeepSeek 判读 -> artifact
"""
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
SHANGHAI = ZoneInfo("Asia/Shanghai")
VALID_REL = {"高", "中", "低", "无关"}
README_PAUSE_SEC = 0.4


class GitHubAuthError(Exception):
    pass


class HttpStatusError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


# ---------- helpers ----------

def _get(ctx, key, default=None):
    if isinstance(ctx, dict):
        return ctx.get(key, default)
    return getattr(ctx, key, default)


def _workspace_dir(ctx):
    env = os.environ.get("DAIMON_BLUEPRINT_AUTOMATION_WORKSPACE_PATH")
    if env and os.path.isdir(env):
        return env
    ws = _get(ctx, "workspacePath") or _get(ctx, "workspace")
    if isinstance(ws, str) and os.path.isdir(ws):
        return ws
    cand = os.path.normpath(os.path.join(ASSETS_DIR, "..", "workspace"))
    os.makedirs(cand, exist_ok=True)
    return cand


def _norm_kw(kw):
    return str(kw or "").strip().strip('"').strip()


def _topic_text(topics):
    if not isinstance(topics, list):
        return ""
    return " ".join(str(t) for t in topics)


def _clean_kws(kws):
    out = []
    for kw in kws or []:
        nk = _norm_kw(kw)
        if nk and nk not in out:
            out.append(nk)
    return out


def _window_dates(window_days, today=None):
    if today is None:
        today = datetime.now(SHANGHAI).date()
    start = today - timedelta(days=max(1, int(window_days)) - 1)
    return start.isoformat(), today.isoformat()


def repo_url(full_name):
    parts = str(full_name).split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return "https://github.com/" + urllib.parse.quote(str(full_name), safe="")
    return "https://github.com/%s/%s" % (
        urllib.parse.quote(parts[0], safe=""),
        urllib.parse.quote(parts[1], safe=""),
    )


def _retry_delay(headers, attempt):
    raw = ""
    if headers is not None:
        raw = headers.get("Retry-After") or ""
    try:
        delay = int(raw)
    except (TypeError, ValueError):
        delay = 2 ** attempt
    return min(max(delay, 1), 20)


def _retryable_status(code, body, headers):
    if code in (429, 502, 503):
        return True
    if code != 403:
        return False
    low = (body or "").lower()
    has_retry = bool(headers is not None and headers.get("Retry-After"))
    return has_retry or ("rate limit" in low)


def _http_json(url, token=None, method="GET", payload=None, timeout=30, raw=False, github=True):
    headers = {"User-Agent": "pharma-repo-radar/1.0"}
    if github:
        headers["Accept"] = "application/vnd.github.raw+json" if raw else "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    else:
        headers["Accept"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    last_error = None
    for attempt in range(4):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            if raw:
                return body
            return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            message = "HTTP %s %s" % (e.code, err_body.replace("\n", " ")[:160])
            if github and e.code == 401:
                raise GitHubAuthError("GitHub 认证失败（HTTP 401）。请更新 githubToken。")
            if attempt < 3 and _retryable_status(e.code, err_body, e.headers):
                time.sleep(_retry_delay(e.headers, attempt))
                last_error = HttpStatusError(e.code, message.strip())
                continue
            raise HttpStatusError(e.code, message.strip())
        except GitHubAuthError:
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_error = e
            if attempt < 2:
                time.sleep(min(2 ** attempt, 8))
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("请求失败")


def _load_secrets(ctx, ws_dir, errors):
    secrets = {}
    inp = _get(ctx, "input") or {}
    if isinstance(inp, dict):
        for k in ("githubToken", "deepseekApiKey"):
            v = inp.get(k)
            if isinstance(v, str) and v.strip():
                secrets[k] = v.strip()
    path = os.path.join(ws_dir, "secrets.json")
    if os.path.isfile(path):
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        try:
            with open(path, "r", encoding="utf-8") as fh:
                file_secrets = json.load(fh)
            if not isinstance(file_secrets, dict):
                raise ValueError("根节点不是对象")
            for k in ("githubToken", "deepseekApiKey"):
                if k not in secrets and file_secrets.get(k):
                    secrets[k] = file_secrets[k]
        except Exception as e:
            errors.append("secrets.json 无法读取: %s" % str(e)[:120])
    for k, env in (("githubToken", "GITHUB_TOKEN"), ("deepseekApiKey", "DEEPSEEK_API_KEY")):
        if k not in secrets and os.environ.get(env):
            secrets[k] = os.environ[env]
    return secrets


def load_state(path):
    if not os.path.isfile(path):
        return {"repos": {}}
    with open(path, "r", encoding="utf-8") as fh:
        loaded = json.load(fh)
    if not isinstance(loaded, dict) or not isinstance(loaded.get("repos"), dict):
        raise ValueError("repos 字段无效")
    return loaded


def atomic_write_json(path, obj):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _or_query(parts):
    return "(" + " OR ".join(parts) + ")"


def pack_keyword_groups(keywords, suffix, limit=240, max_terms=6):
    """GitHub 搜索最多允许 5 个 OR，因此每组最多 6 个词。"""
    groups = []
    current = []
    for kw in keywords:
        trial = current + [kw]
        query = _or_query(trial) + suffix
        if current and (len(query) > limit or len(trial) > max_terms):
            groups.append(current)
            current = [kw]
        else:
            current = trial
    if current:
        groups.append(current)
    return groups


def build_search_plan(cfg, date_from):
    plan = []
    date_from = date_from + "T00:00:00+08:00"
    tier_suffix = " created:>=%s in:name,description,readme,topics" % date_from
    for group in pack_keyword_groups(cfg.get("tier1_keywords") or [], tier_suffix):
        plan.append((_or_query(group) + tier_suffix, "一级关键词", "tier1"))
    for group in pack_keyword_groups(cfg.get("tier2_keywords") or [], tier_suffix):
        plan.append((_or_query(group) + tier_suffix, "二级关键词", "tier2"))
    orgs = ["user:%s" % org for org in (cfg.get("watch_orgs") or []) if org]
    org_suffix = " created:>=%s" % date_from
    for org in orgs:
        plan.append((org + org_suffix, org, "org"))
    return plan


# ---------- github search ----------

def gh_search(query, token, errors, label):
    url = ("https://api.github.com/search/repositories?q="
           + urllib.parse.quote(query + " is:public") + "&per_page=100&sort=created&order=desc")
    try:
        data = _http_json(url, token=token, timeout=40)
    except GitHubAuthError:
        raise
    except Exception as e:
        errors.append("搜索失败 [%s]: %s" % (label, str(e)[:160]))
        return None
    items = data.get("items") or []
    total = int(data.get("total_count") or 0)
    if total > len(items):
        errors.append("%s 命中 %d 条，仅取最新 %d 条" % (label, total, len(items)))
    return items


def gh_readme(full_name, token):
    parts = str(full_name).split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return ""
    url = "https://api.github.com/repos/%s/%s/readme" % (
        urllib.parse.quote(parts[0], safe=""),
        urllib.parse.quote(parts[1], safe=""),
    )
    try:
        return _http_json(url, token=token, timeout=30, raw=True) or ""
    except GitHubAuthError:
        raise
    except HttpStatusError as e:
        if e.code == 404:
            return ""
        return None
    except Exception:
        return None


# ---------- keyword verification ----------

def verify_tier1(kw, text):
    k = _norm_kw(kw).lower()
    t = (text or "").lower()
    if not k:
        return False
    if k == "define.xml":
        return ("define.xml" in t) or ("define-xml" in t) or ("define xml" in t)
    if k == "pinnacle 21":
        return ("pinnacle 21" in t) or ("pinnacle21" in t)
    return k in t


def verify_tier2(kw, text, context_words):
    raw = text or ""
    tl = raw.lower()
    has_context = any(str(cw).lower() in tl for cw in (context_words or []))
    if not has_context:
        return False
    if kw == "ADaM":
        return re.search(r"\bADaM\b", raw) is not None
    if kw == "P21":
        return ("pinnacle 21" in tl) or ("pinnacle21" in tl) or re.search(r"\bP21\b", raw) is not None
    return re.search(r"\b" + re.escape(kw) + r"\b", raw, re.IGNORECASE) is not None


def scan_keywords(text, cfg):
    matched = []
    for kw in cfg.get("tier1_keywords") or []:
        if verify_tier1(kw, text):
            nk = _norm_kw(kw)
            if nk and nk not in matched:
                matched.append(nk)
    ctx = cfg.get("context_words") or []
    for kw in cfg.get("tier2_keywords") or []:
        if verify_tier2(kw, text, ctx):
            nk = _norm_kw(kw)
            if nk and nk not in matched:
                matched.append(nk)
    return matched


def _priority(c, tier2_set):
    if c.get("isOrgWatch"):
        return 0
    if c.get("fromTier1"):
        return 1
    if any(kw not in tier2_set for kw in c.get("matched") or []):
        return 1
    return 2


# ---------- deepseek ----------

def _parse_verdict_payload(content):
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    rows = parsed.get("results") if isinstance(parsed, dict) else None
    if not isinstance(rows, list):
        return {}
    out = {}
    for row in rows:
        if isinstance(row, dict) and row.get("repo"):
            out[str(row["repo"])] = {
                "relevance": str(row.get("relevance", "")).strip(),
                "summary": str(row.get("summary", "")).strip(),
            }
    return out


def _deepseek_batch(batch, api_key, model):
    lines = []
    for cand in batch:
        lines.append(json.dumps({
            "repo": cand["repo"],
            "description": cand.get("description") or "",
            "matched_keywords": cand.get("matched") or [],
            "readme_excerpt": (cand.get("readme") or "")[:1200],
        }, ensure_ascii=False))
    prompt = (
        "你是医药行业的资深 Statistical Programmer。下面是 GitHub 上最近新建的候选仓库列表（JSON 行）。"
        "请逐个判断它与药企统计编程（CDISC/SDTM/ADaM/TLF/Define.xml/Pinnacle 21/SAS/临床试验数据递交等）的真实相关性，"
        "并用一句简体中文概括这个仓库是做什么的、与上述领域哪块相关。\n"
        "只输出一个 JSON 对象，格式：{\"results\":[{\"repo\":\"owner/name\",\"relevance\":\"高|中|低|无关\",\"summary\":\"一句中文摘要\"}]}。"
        "relevance 只能是 高/中/低/无关 之一。以下情况一律判为 无关：深度学习 Adam 优化器、人名撞车、"
        "通用统计/实验设计课程教材、与医药临床数据标准无直接关系的仓库。\n\n"
        + "\n".join(lines)
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是医药统计编程专家，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": 2500,
    }
    data = _http_json(
        "https://api.deepseek.com/chat/completions",
        token=api_key,
        method="POST",
        payload=payload,
        timeout=180,
        github=False,
    )
    content = data["choices"][0]["message"]["content"]
    return _parse_verdict_payload(content)


def deepseek_judge(candidates, api_key, model, errors):
    if not candidates:
        return {}
    if not api_key:
        errors.append("未配置 DeepSeek API Key，新仓库标为待确认，下次运行会重试")
        return {}
    out = {}
    size = 8
    for i in range(0, len(candidates), size):
        batch = candidates[i:i + size]
        if i:
            time.sleep(0.5)
        try:
            out.update(_deepseek_batch(batch, api_key, model))
        except Exception as e:
            errors.append("DeepSeek 判读失败（第 %d-%d 个）: %s" % (
                i + 1, i + len(batch), str(e)[:150]))
    return out


def fallback_summary(cand):
    kws = "、".join(_clean_kws(cand.get("matched")))
    desc = (cand.get("description") or "").strip()
    if kws:
        head = "命中关键词：%s。" % kws
    elif cand.get("isOrgWatch"):
        head = "来自监控组织的新仓库。"
    else:
        head = "尚未完成相关性判读。"
    tail = ("简介：" + desc[:80]) if desc else "仓库暂无描述。"
    return head + tail


def apply_verdict(cand, verdict):
    if isinstance(verdict, dict) and verdict.get("relevance") in VALID_REL:
        summary = str(verdict.get("summary") or "").strip() or fallback_summary(cand)
        return {"relevance": verdict["relevance"], "summary": summary, "needsJudge": False}
    return {"relevance": "待确认", "summary": fallback_summary(cand), "needsJudge": True}


def _star_count(item, prev):
    if item is not None and item.get("stargazers_count") is not None:
        return int(item.get("stargazers_count") or 0)
    return int((prev or {}).get("stars") or 0)


def _blank_candidate(name, item, prev):
    rejudge = bool(prev and prev.get("needsJudge"))
    return {
        "repo": name,
        "url": repo_url(name),
        "createdAt": (item or {}).get("created_at") or (prev or {}).get("createdAt") or "",
        "description": (item or {}).get("description") or (prev or {}).get("description") or "",
        "language": (item or {}).get("language") or (prev or {}).get("language") or "",
        "stars": _star_count(item, prev),
        "topics": (item or {}).get("topics") or [],
        "matched": [],
        "isOrgWatch": bool((prev or {}).get("isOrgWatch")),
        "fromTier1": False,
        "rejudge": rejudge,
        "countAsNew": not rejudge,
        "readme": "",
        "thin": False,
        "isLookback": False,
    }


def _note_for_run(auth_error, plan, search_ok, display, total_new, display_days):
    if auth_error:
        if display:
            return "GitHub 认证失败，请更新 githubToken。下面只展示最近已收录的仓库。"
        return "GitHub 认证失败，请更新 githubToken。本次没有抓到新仓库。"
    if plan and search_ok == 0:
        if display:
            return "本次 GitHub 搜索失败，下面是最近已收录的仓库。"
        return "本次 GitHub 搜索失败，没有可展示的新仓库。"
    if not display:
        return "近期无相关仓库"
    if total_new == 0:
        return "本次运行无新增，以下展示最近 %d 天收录" % display_days
    return ""


def _error_artifact(now, date_from, date_to, note, errors):
    return {
        "artifact": {
            "generatedAt": now.isoformat(),
            "windowStart": date_from,
            "windowEnd": date_to,
            "totalNew": 0,
            "note": note,
            "errors": "；".join(errors),
            "repos": [],
        }
    }


# ---------- main ----------

def run(ctx):
    errors = []
    with open(os.path.join(ASSETS_DIR, "radar_config.json"), "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    now = datetime.now(timezone.utc)
    window_days = int(cfg.get("window_days", 2))
    date_from, date_to = _window_dates(window_days)
    ws_dir = _workspace_dir(ctx)
    secrets = _load_secrets(ctx, ws_dir, errors)
    token = secrets.get("githubToken")
    ds_key = secrets.get("deepseekApiKey")

    state_file = os.path.join(ws_dir, "seen_repos.json")
    try:
        state = load_state(state_file)
    except Exception as e:
        errors.append("状态文件无法读取，本次已停止，避免把已收录仓库清空重置: %s" % str(e)[:120])
        return _error_artifact(
            now, date_from, date_to,
            "状态文件损坏，本次未抓取。请检查 workspace/seen_repos.json。",
            errors,
        )
    seen = state.setdefault("repos", {})
    for meta in list(seen.values()):
        if isinstance(meta, dict):
            meta["matched"] = _clean_kws(meta.get("matched"))

    candidates = {}
    search_gap = 2.3 if token else 6.5
    tier2_set = {_norm_kw(kw) for kw in (cfg.get("tier2_keywords") or [])}
    plan = build_search_plan(cfg, date_from)
    auth_error = None
    search_ok = 0

    def fail_auth(exc):
        nonlocal auth_error
        if not auth_error:
            auth_error = str(exc)
            errors.append(auth_error)

    def add_item(item, origin):
        name = item.get("full_name")
        if not name:
            return
        prev = seen.get(name)
        if prev and not prev.get("needsJudge"):
            return
        cand = candidates.setdefault(name, _blank_candidate(name, item, prev if isinstance(prev, dict) else None))
        if item.get("stargazers_count") is not None:
            cand["stars"] = int(item.get("stargazers_count") or 0)
        if origin == "tier1":
            cand["fromTier1"] = True
        if origin == "org":
            cand["isOrgWatch"] = True
        text = " ".join([name, cand.get("description") or "", _topic_text(cand.get("topics"))])
        for kw in scan_keywords(text, cfg):
            if kw not in cand["matched"]:
                cand["matched"].append(kw)

    for i, (query, label, origin) in enumerate(plan):
        if auth_error:
            break
        if i > 0:
            time.sleep(search_gap)
        try:
            items = gh_search(query, token, errors, label)
        except GitHubAuthError as exc:
            fail_auth(exc)
            break
        if items is None:
            continue
        search_ok += 1
        for item in items:
            if item.get("private", True):
                continue
            add_item(item, origin)
        print("[search] %s -> %d hits" % (label, len(items)))

    print("[filter] raw candidates: %d" % len(candidates))

    readme_budget_total = int(cfg.get("max_readme_fetches", 90))
    budget = readme_budget_total
    budget_warned = False
    verified = []

    def take_readme(name):
        nonlocal budget, budget_warned, auth_error
        if auth_error:
            return None
        if budget <= 0:
            if not budget_warned:
                errors.append("README 拉取达到上限 %d，剩余候选跳过" % readme_budget_total)
                budget_warned = True
            return None
        try:
            readme = gh_readme(name, token)
        except GitHubAuthError as exc:
            fail_auth(exc)
            return None
        budget -= 1
        time.sleep(README_PAUSE_SEC)
        return readme

    ordered = sorted(candidates.items(), key=lambda kv: kv[1].get("createdAt") or "", reverse=True)
    ordered.sort(key=lambda kv: _priority(kv[1], tier2_set))
    for name, cand in ordered:
        if auth_error:
            break
        if budget <= 0:
            if not budget_warned:
                errors.append("README 拉取达到上限 %d，剩余候选跳过" % readme_budget_total)
                budget_warned = True
            break
        readme = take_readme(name)
        if auth_error:
            break
        if readme is None:
            errors.append("README 暂时拉不下来: %s" % name)
            continue
        cand["readme"] = readme
        text = " ".join([
            name,
            cand.get("description") or "",
            _topic_text(cand.get("topics")),
            readme,
        ])
        found = scan_keywords(text, cfg)
        if found:
            cand["matched"] = found
        ok = bool(found) or cand.get("isOrgWatch")
        if not ok:
            if cand.get("rejudge"):
                prev = seen.get(name)
                if isinstance(prev, dict):
                    prev["needsJudge"] = False
                    prev["relevance"] = "无关"
                    prev["summary"] = prev.get("summary") or "未通过关键词复核"
            continue
        cand["thin"] = len(readme.strip()) < 100
        verified.append(cand)

    lookback = []
    lookback_days = int(cfg.get("lookback_days", 7))
    cutoff = (now - timedelta(days=lookback_days)).isoformat()
    for name, meta in list(seen.items()):
        if auth_error:
            break
        if not isinstance(meta, dict):
            continue
        thin = bool(meta.get("thin"))
        if thin and meta.get("firstSeen", "") < cutoff:
            meta["thin"] = False
            thin = False
        need_judge = bool(meta.get("needsJudge")) and meta.get("firstSeen", "") >= cutoff
        if not thin and not need_judge:
            continue
        if name in candidates:
            continue
        if budget <= 0:
            if not budget_warned:
                errors.append("README 拉取达到上限 %d，剩余回看跳过" % readme_budget_total)
                budget_warned = True
            break
        readme = take_readme(name)
        if auth_error or budget_warned:
            break
        if readme is None:
            errors.append("README 暂时拉不下来: %s" % name)
            continue
        text = " ".join([name, meta.get("description") or "", readme])
        found = scan_keywords(text, cfg)
        still_thin = len(readme.strip()) < 100
        if not found and not meta.get("isOrgWatch"):
            meta["needsJudge"] = False
            meta["relevance"] = "无关"
            meta["thin"] = still_thin
            meta["summary"] = meta.get("summary") or "未通过关键词复核"
            continue
        if thin and not still_thin:
            entry = _blank_candidate(name, None, meta)
            entry.update({
                "readme": readme,
                "matched": found or _clean_kws(meta.get("matched")),
                "thin": False,
                "isLookback": True,
                "rejudge": need_judge,
                "countAsNew": True,
                "isOrgWatch": bool(meta.get("isOrgWatch")),
            })
            lookback.append(entry)
            meta["thin"] = False
            continue
        if need_judge:
            entry = _blank_candidate(name, None, meta)
            entry.update({
                "readme": readme,
                "matched": found or _clean_kws(meta.get("matched")),
                "thin": still_thin,
                "isLookback": False,
                "rejudge": True,
                "countAsNew": False,
                "isOrgWatch": bool(meta.get("isOrgWatch")),
            })
            lookback.append(entry)

    print("[verify] verified new: %d, lookback hits: %d" % (len(verified), len(lookback)))

    all_cands = verified + lookback
    verdicts = {}
    if all_cands:
        verdicts = deepseek_judge(all_cands, ds_key, cfg.get("deepseek_model", "deepseek-chat"), errors)

    judge_map = {}
    for cand in all_cands:
        judged = apply_verdict(cand, verdicts.get(cand["repo"]))
        cand["needsJudge"] = judged["needsJudge"]
        judge_map[cand["repo"]] = judged

    for cand in all_cands:
        judged = judge_map.get(cand["repo"], {})
        prev = seen.get(cand["repo"]) if isinstance(seen.get(cand["repo"]), dict) else {}
        seen[cand["repo"]] = {
            "firstSeen": (prev or {}).get("firstSeen") or now.isoformat(),
            "createdAt": cand.get("createdAt", ""),
            "description": (cand.get("description") or "")[:300],
            "language": cand.get("language", ""),
            "stars": cand.get("stars", 0),
            "matched": _clean_kws(cand.get("matched")),
            "isOrgWatch": bool(cand.get("isOrgWatch")),
            "thin": bool(cand.get("thin")),
            "needsJudge": bool(judged.get("needsJudge")),
            "relevance": judged.get("relevance", "待确认"),
            "summary": judged.get("summary", ""),
        }

    prune_before = (now - timedelta(days=45)).isoformat()
    for name in list(seen.keys()):
        meta = seen.get(name)
        if isinstance(meta, dict) and meta.get("firstSeen", "") < prune_before:
            del seen[name]
    try:
        atomic_write_json(state_file, state)
    except Exception as e:
        errors.append("状态写入失败: %s" % str(e)[:100])

    display_days = int(cfg.get("display_days", 3))
    display_cutoff = (now - timedelta(days=display_days)).isoformat()
    new_names = {cand["repo"] for cand in all_cands if cand.get("countAsNew")}
    lb_names = {cand["repo"] for cand in lookback if cand.get("isLookback")}
    display = []
    for name, meta in seen.items():
        if not isinstance(meta, dict):
            continue
        if meta.get("relevance") == "无关":
            continue
        if meta.get("needsJudge"):
            relevance = "待确认"
        else:
            relevance = meta.get("relevance") or "中"
        if relevance == "无关":
            continue
        if meta.get("firstSeen", "") < display_cutoff:
            continue
        summary = meta.get("summary") or ""
        if not summary:
            summary = fallback_summary({
                "matched": meta.get("matched", []),
                "description": meta.get("description", ""),
                "isOrgWatch": meta.get("isOrgWatch"),
            })
        display.append({
            "repo": name,
            "url": repo_url(name),
            "createdAt": meta.get("createdAt", ""),
            "description": meta.get("description", ""),
            "language": meta.get("language", ""),
            "stars": int(meta.get("stars") or 0),
            "matchedKeywords": _clean_kws(meta.get("matched")),
            "relevance": relevance,
            "summary": summary,
            "isOrgWatch": bool(meta.get("isOrgWatch")),
            "isLookback": name in lb_names,
            "isNew": name in new_names,
        })

    rank = {"高": 0, "中": 1, "低": 2, "待确认": 3}
    display.sort(key=lambda row: row["createdAt"], reverse=True)
    display.sort(key=lambda row: rank.get(row["relevance"], 4))

    total_new = sum(1 for row in display if row["isNew"])
    note = _note_for_run(auth_error, plan, search_ok, display, total_new, display_days)
    artifact = {
        "generatedAt": now.isoformat(),
        "windowStart": date_from,
        "windowEnd": date_to,
        "totalNew": total_new,
        "note": note,
        "errors": "；".join(errors),
        "repos": display,
        "watchAccounts": cfg.get("watch_orgs", []),
    }
    print("[done] new this run: %d, display total: %d, errors: %d" % (total_new, len(display), len(errors)))
    return {"artifact": artifact}
