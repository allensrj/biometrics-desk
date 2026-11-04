const el = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const href = (value) => (/^https?:\/\//i.test(value) ? esc(value) : "#");
const out = (url, label) =>
  '<a target="_blank" rel="noopener noreferrer" href="' +
  href(url) +
  '">' +
  esc(label) +
  "</a>";

async function start() {
  const load = async (path) => {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw Error(path);
    return response.json();
  };
  let [clinical, github, status, archive] = await Promise.all(
    [
      "clinical.json",
      "repositories.json",
      "refresh-status.json",
      "repositories-archive.json",
    ].map(load),
  );
  const bj = (value) =>
    new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(new Date(value));
  const defaults = {
    tab: "临床情报",
    rank: "",
    category: "",
    day: "",
    due: false,
    archive: false,
  };
  let state = { ...defaults };
  const repoTab = "开源仓库";
  const today = () =>
    new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(
      new Date(),
    );
  const daysUntil = (date) =>
    (Date.parse(date) - Date.parse(today())) / 86400000;
  const upcoming = (i) =>
    i.deadline && daysUntil(i.deadline) >= 0 && daysUntil(i.deadline) <= 30;
  const relevanceOrder = { 高: 0, 中: 1, 低: 2, 待确认: 3 };
  const repoRows = () =>
    (state.archive ? archive : github).repos
      .map((r) => ({
        ...r,
        title: r.repo,
        rank: r.relevance,
        category: "开源仓库",
        tags: r.matchedKeywords || [],
      }))
      .sort(
        (a, b) =>
          (relevanceOrder[a.rank] ?? 4) - (relevanceOrder[b.rank] ?? 4) ||
          (Date.parse(b.createdAt) || 0) - (Date.parse(a.createdAt) || 0),
      );
  const clinicalRows = (items = clinical.items) =>
    items.map((i) => ({ ...i, rank: i.importance }));
  const btn = (action, value, label, attrs = "") =>
    `<button type="button" data-action="${action}" data-value="${esc(value)}" ${attrs}>${label}</button>`;
  const pressed = (value) => 'aria-pressed="' + Boolean(value) + '"';
  const select = (id, label, values, value) =>
    `<select id="${id}" aria-label="${label}"><option value="">${label}</option>${values.map((v) => `<option ${v === value ? "selected" : ""} value="${esc(v)}">${esc(v)}</option>`).join("")}</select>`;
  function navigate(patch, query = "") {
    state = { ...defaults, ...patch };
    el("query").value = query;
    renderDashboard();
    el("results").focus({ preventScroll: true });
    el("results").scrollIntoView({ block: "start" });
  }
  function record(i) {
    const repo = Boolean(i.repo),
      tags = i.tags || [];
    const rank = repo
      ? i.rank === "待确认"
        ? "待确认"
        : i.rank + "相关"
      : i.rank + "重要度";
    const date = repo
      ? i.createdAt
        ? bj(i.createdAt).split(" ")[0] + " 创建"
        : ""
      : i.agendaOnly
        ? "事项日期 " + i.deadline
        : i.published + " 发布";
    const meta = repo ? i.repo.split("/")[0] : i.category;
    return `<article class="entry ${repo ? "repo" : ""}" data-record-url="${esc(i.url)}" tabindex="-1"><div class="meta"><span class="badge ${{ 高: "rank-high", 中: "rank-medium", 低: "rank-low" }[i.rank] || ""}">${esc(rank)}</span><span>${esc(meta)}</span><time>${esc(date)}</time></div><h3>${repo ? out(i.url, i.repo.split("/").slice(1).join("/")) : esc(i.title)}</h3><p>${esc(i.summary || i.description)}</p>${i.impact ? "<details><summary>对统计编程的影响</summary><p>" + esc(i.impact) + "</p></details>" : ""}<div class="tags">${tags.map((t) => btn("tag", t, esc(t), 'class="tag" title="搜索此关键词"')).join("")}</div><footer><span>${esc(repo ? [i.language, "☆ " + (i.stars || 0), i.isOrgWatch ? "关注账号" : "", i.isLookback ? "回看补录" : "", i.isNew ? "本期收录" : ""].filter(Boolean).join("　") : i.source)}</span>${i.deadline ? btn("date", i.deadline, esc(i.deadline), 'class="tag" title="查看同日事项"') : ""}${out(i.url, repo ? "访问仓库" : "阅读原文")}</footer></article>`;
  }
  function renderDashboard() {
    const news = clinicalRows(),
      repos = repoRows(),
      isRepo = state.tab === repoTab;
    const calendar = news.concat(
      clinicalRows(clinical.agendaOnly || []).map((i) => ({
        ...i,
        agendaOnly: true,
      })),
    );
    const all = state.due || state.day ? calendar : isRepo ? repos : news;
    const query = el("query").value.trim().toLowerCase();
    const visible = all.filter(
      (i) =>
        (!state.rank || i.rank === state.rank) &&
        (!state.category || i.category === state.category) &&
        (!state.day || i.deadline === state.day) &&
        (!state.due || upcoming(i)) &&
        (!query ||
          [
            i.title,
            i.summary,
            i.impact,
            i.source,
            i.language,
            i.category,
            ...(i.tags || []),
          ]
            .join(" ")
            .toLowerCase()
            .includes(query)),
    );
    if (state.due || state.day)
      visible.sort((a, b) => a.deadline.localeCompare(b.deadline));
    const soon = calendar
      .filter(upcoming)
      .sort((a, b) => a.deadline.localeCompare(b.deadline));
    const groups = [...new Set(news.map((i) => i.category))].sort(
      (a, b) =>
        news.filter((i) => i.category === b).length -
        news.filter((i) => i.category === a).length,
    );
    const metrics = [
      ["clinical", "临床情报", news.length],
      ["high", "高重要度情报", news.filter((i) => i.rank === "高").length],
      ["due", "30 天内事项", soon.length],
      ["repo", "开源仓库", github.repos.length],
    ];
    el("metrics").innerHTML = metrics
      .map(([key, label, n]) => {
        const active =
          !query &&
          !state.category &&
          !state.day &&
          !state.archive &&
          (key === "repo"
            ? isRepo && !state.rank
            : state.tab === "临床情报" &&
              (key === "high"
                ? state.rank === "高" && !state.due
                : key === "due"
                  ? state.due
                  : !state.rank && !state.due));
        return btn(
          "metric",
          key,
          `<span>${label}</span><b>${n}</b><i aria-hidden="true">↳</i>`,
          `class="metric ${key}" ${pressed(active)} aria-label="${label}，${n} 条"`,
        );
      })
      .join("");
    el("issue").textContent = new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "long",
    }).format(new Date());
    const days = [...new Set(soon.map((i) => i.deadline))];
    el("timeline").innerHTML =
      days
        .map((d, index) => {
          const items = soon.filter((i) => i.deadline === d);
          const left = (daysUntil(d) / 30) * 100;
          return `<div class="tick-wrap" style="--x:${left}%"><button type="button" class="tick ${index % 2 ? "lower" : ""}" aria-label="${esc(d)}，${items.length} 项" aria-describedby="day-${index}"><span>${esc(d.slice(5).replace("-", "/"))}</span></button><div role="group" aria-label="${esc(d)} 的事项" id="day-${index}" class="day-tip" style="--align:${left > 60 ? "-100%" : left > 30 ? "-50%" : "0%"}"><b>${esc(d)}　${items.length} 项</b>${items.map((i) => `<a class="day-item" href="#results" data-action="item" data-value="${esc(i.url)}" title="在看板中查看此事项"><strong>${esc(i.title)}</strong><small>${esc(i.source)}</small></a>`).join("")}</div></div>`;
        })
        .join("") || '<span class="empty-axis">暂无已知日程</span>';
    el("tabs").innerHTML = ["临床情报", repoTab]
      .map((t) => btn("tab", t, t, pressed(t === state.tab)))
      .join("");
    el("context").innerHTML =
      `<b>${visible.length} 条结果</b> ${state.tab === "临床情报" && !state.due && !state.day ? "近 90 天 · 按发布日期倒序" : ""} ${state.due ? "未来 30 天 " : ""}${esc(state.day)} ${select("rank", isRepo ? "所有相关性" : "所有重要度", isRepo ? ["高", "中", "低", "待确认"] : ["高", "中", "低"], state.rank)}${state.tab === "临床情报" ? select("category", "所有主题", groups, state.category) : ""}${isRepo ? select("edition", "本期简报", ["历史简报"], state.archive ? "历史简报" : "") : ""}`;
    if (isRepo)
      el("context").insertAdjacentHTML(
        "beforeend",
        "<small>相关性优先，同档按创建时间从新到旧</small>",
      );
    el("reset").hidden = !(
      state.rank ||
      state.category ||
      state.day ||
      state.due ||
      state.archive ||
      query
    );
    el("feed").className = isRepo ? "repo-grid" : "";
    el("feed").innerHTML =
      visible.map(record).join("") ||
      '<div class="empty">没有符合当前条件的记录。 ' +
        btn("clear", "", "清除筛选", 'class="tag"') +
        "</div>";
    el("categories").innerHTML = groups
      .map((g) => {
        const n = news.filter((i) => i.category === g).length;
        return btn(
          "group",
          g,
          `<span>${esc(g)}</span><i style="--pct:${(100 * n) / news.length}%"></i><b>${n}</b>`,
          'class="bar" ' + pressed(state.category === g),
        );
      })
      .join("");
    el("dates").innerHTML =
      soon
        .slice(0, 5)
        .map((i) =>
          btn(
            "date",
            i.deadline,
            "<time>" +
              esc(i.deadline.slice(5).replace("-", "/")) +
              "</time><span>" +
              esc(i.title) +
              "</span>",
            'class="event"',
          ),
        )
        .join("") || "<p>未来 30 天暂无已知日程。</p>";
    const stamp = (v) => (v ? bj(v) + "（北京时间）" : "暂无记录");
    const sources = (clinical.sources || []).map((s) => out(s.url, s.name)).join("、");
    const sourceIssues = (clinical.sources || []).filter((s) => !s.ok || s.limited || s.pendingAnalysis)
      .map((s) => esc(s.name) + "：" + esc([
        s.error ? (s.read ? "部分内容未能采集" : "本轮未能采集") : "",
        s.limited ? "采集范围不完整" : "",
        s.pendingAnalysis ? s.pendingAnalysis + " 条分析待重试" : "",
        s.retained ? "保留本项目此前核实的内容" : ""
      ].filter(Boolean).join("；"))).join("<br>");
    const releases = (github.releases || [])
      .map(
        (r) => `<li>${out(r.url, r.repo + " " + r.tag)} · ${bj(r.date)}</li>`,
      )
      .join("");
    const panel = el("release-watch");
    panel.hidden = !isRepo || state.archive;
    panel.innerHTML = `<summary>关注账号的正式发布（${github.releases?.length || 0}）</summary><p>近五天有推送的相关公开项目，新仓库另列于下方。</p>${releases ? "<ul>" + releases + "</ul>" : "<p>当前窗口未收录正式发布。</p>"}${github.releaseErrors?.length ? "<p>检查未完成：" + esc(github.releaseErrors.join("、")) + "</p>" : ""}`;
    el("updates").innerHTML =
      `<div class="sync"><b>临床情报</b>采集完成　${stamp(status.clinical?.checked)}<p>${"来源：" + sources}</p><p>独立采集官网 · 近 90 个北京时间自然日</p>${sourceIssues ? "<p class=\"source-warning\">" + sourceIssues + "</p>" : ""}<p><a href="collection-report.json" target="_blank" rel="noopener">查看本轮采集记录 ↗</a></p></div><div class="sync"><b>开源仓库</b><p>采集范围　${esc(github.windowStart)} 至 ${esc(github.windowEnd)}（北京时间）</p></div>`;
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-action]");
    if (!b) return;
    const { action, value } = b.dataset;
    if (action === "metric")
      navigate(
        {
          high: { rank: "高" },
          due: { due: true },
          repo: { tab: repoTab },
          clinical: {},
        }[value],
      );
    if (action === "item") {
      e.preventDefault();
      const item = [...clinical.items, ...(clinical.agendaOnly || [])].find(
        (entry) => entry.url === value,
      );
      if (!item) return;
      navigate({ day: item.deadline });
      const target = [...el("feed").querySelectorAll("article")].find(
        (entry) => entry.dataset.recordUrl === value,
      );
      if (target) {
        target.classList.add("located");
        target.focus({ preventScroll: true });
        target.scrollIntoView({ block: "center" });
      }
    }
    if (action === "date") navigate({ day: value });
    if (action === "group") navigate({ category: value });
    if (action === "tab") navigate({ tab: value }, el("query").value);
    if (action === "tag")
      navigate({ tab: state.tab, archive: state.archive }, value);
    if (action === "clear") navigate({ tab: state.tab });
  });
  el("context").onchange = (e) => {
    const { id, value } = e.target;
    if (id === "edition") {
      state.archive = Boolean(value);
      state.rank = "";
    } else if (id === "rank" || id === "category") state[id] = value;
    renderDashboard();
    el(id)?.focus();
  };
  el("reset").onclick = () => navigate({ tab: state.tab });
  el("query").oninput = renderDashboard;
  renderDashboard();

  let checking = false;
  async function sync() {
    if (document.hidden || checking) return;
    checking = true;
    try {
      const next = await load("refresh-status.json");
      if (JSON.stringify(next) !== JSON.stringify(status)) {
        const fresh = await Promise.all(
          ["clinical.json", "repositories.json"].map(load),
        );
        [clinical, github] = fresh;
        status = next;
        renderDashboard();
      }
    } catch {
      /* Keep the visible edition while the local server is offline. */
    } finally {
      checking = false;
    }
  }
  setInterval(sync, 60000);
  document.addEventListener("visibilitychange", sync);
}
start().catch(
  () =>
    (el("feed").textContent =
      "数据加载失败，请稍后刷新页面重试。"),
);
