# 临床统计编程信息看板 · Biometrics Desk

[打开在线看板](https://allensrj.github.io/biometrics-desk/) · [每日更新记录](https://github.com/allensrj/biometrics-desk/actions/workflows/dashboard.yml)

面向药企临床统计编程人员的信息看板，把法规、数据标准、行业动态和相关开源工具放在一个页面里。使用者可以快速浏览近期更新，筛选重要情报，查看未来事项，再通过原文链接核实细节。

页面包含「临床情报」和「开源仓库」两个部分。高、中、低等级统一使用灰红、灰黄、灰绿色标记，并保留文字说明。搜索、主题筛选和首页数字均可直接操作。未来 30 天的事项在时间轴上展示，悬停可以预览，点击事项可以定位到看板中的对应条目。

## 临床情报

**本项目独立访问官方网站、独立筛选并调用 DeepSeek 分析，不再读取任何第三方看板的汇总 JSON。** 参考项目只用于开发思路与历史代码署名，其是否更新不影响本项目采集。

收录最近 **90 个北京时间自然日（含当天）**的新闻，按官网发布日期从新到旧排序。官网提供带时区时间戳时转为北京时间；只提供日期时保留官方日期。文件索引采用文件自身的明确版本日期，不采用首页更新时间、HTTP Last-Modified 或本次抓取时间。没有可靠发布日期的内容不进入新闻列表；有官方明确未来截止日的通知可以仅进入近期事项。

| 官方来源 | 直接读取范围 | 日期和内容依据 |
| --- | --- | --- |
| [CDISC](https://www.cdisc.org/news/whats-new) | What's New、Newsroom、公开征求意见、近期网络研讨会目录与文章 | 新闻目录日期、正文 Published Date；截止日单独记录 |
| [CDE](https://www.cde.org.cn/) | 药审中心首页公告、工作动态目录及公告原文 | 公告目录/正文发布日期。栏目或正文受限时明确标注；仅取得目录的条目不推断指南内容 |
| [ICH](https://www.ich.org/) | ICH 官网使用的官方 CMS 新闻接口，分页读取文章正文 | 官网新闻 `date` 字段，不用 CMS 编辑时间冒充新发布 |
| [FDA](https://www.fda.gov/drugs/guidances-drugs/newly-added-guidance-documents) | Newly Added Guidance Documents 目录及对应指南页面 | 指南目录 Issue Date；读取失败会显示在来源状态中 |
| [PHUSE](https://phuse.global/Communications/PHUSE_Blog) | 官网 CMS 分页读取 Blog 的行业、工作组与会议文章 | 官网 CMS `date_published` 字段与文章原文 |
| [美国联邦公报](https://www.federalregister.gov/agencies/food-and-drug-administration) | 官方 API 的 FDA 公告，按 90 天日期条件分页检索 | `publication_date` 和官方摘要；不声称读过全文 |
| [PMDA](https://www.pmda.go.jp/english/review-services/reviews/0002.html) | 电子研究数据标准目录与最新验证规则 | 资料索引的明确文件/版本日期 |
| [NCI EVS](https://evs.nci.nih.gov/ftp1/CDISC/) | SDTM、ADaM 受控术语发布文件 | 文件内标注的术语版本日期 |
| [EMA](https://www.ema.europa.eu/en/about-us/how-we-work/data-regulation-big-data-other-sources/use-clinical-study-data-medicine-evaluation) | 临床研究数据试点说明、问答和配套文件索引 | 各文件自身发布日期或修订日期 |

抓取后先按日期和领域词筛选候选，再将**实际取得的正文、官方摘要或资料索引**交给 DeepSeek 判断相关性、生成中文标题/摘要/影响说明，并标记高、中、低重要度。模型不能更改原文链接、发布日期或截止日；通过原文证据片段校验后才收录。高重要度强调对研究设计、分析、标准或递交有实质影响，中重要度强调实际工作价值，低重要度保留相关背景信息。纯药物审批、招聘、商业宣传等不会因为来源权威而自动收录。

每站独立采集，**“没有近期内容”和“采集失败”分开记录**。失败时只允许保留本项目此前独立核实、仍在日期窗口内的内容，首次迁移不会把旧的第三方汇总当作兜底数据。分析失败的候选留待下次重试，不伪装成已完成情报。相同内容的分析结果按内容摘要缓存；每轮最多分析 160 个新候选，按来源轮流分配，积压数量公开记录。

90 天是**收录窗口，不是全网完整覆盖保证**。各站范围限于上表的官方入口；滚动目录、分页上限、访问限制和缺少发布日期都会影响覆盖。达到上限或读取不完整时会在网页来源说明中标注，不用旧文件补足来源数量。[本轮采集记录](https://allensrj.github.io/biometrics-desk/collection-report.json) 提供各站读取/收录数、日期证据、待重试项与最新收录日期；Actions 运行摘要也列出逐站结果。

实现入口：[采集适配器](collector/clinical_sources.py)、[独立分析](collector/clinical_analysis.py)、[日期筛选与数据来源记录](collector/clinical_pipeline.py)。

## 开源仓库

通过 GitHub API 检索最近 **5 个北京时间自然日（含当天）**创建的相关公开仓库。关键词分两级，第一类围绕 CDISC、SDTM、ADaMIG 等专业标准，另一类如 SAS、ADaM、TFL 需要结合临床与医药上下文核验。候选仓库进一步读取 README，由 DeepSeek 生成中文摘要与高、中、低相关性判读，判读失败时标为「待确认」并留待重试。

已收录仓库会去重，对内容较少或尚未完成判读的候选做七天回看。列表按相关性优先排列，同一档内按仓库创建时间倒序排列。GitHub 搜索结果与 README 请求数量设有上限，因此每次收录有数量边界。

还会检查关注账号中近期有推送的相关公开项目，单列正式 Release。当前范围包括 pharmaverse、cdisc-org、phuse-org、RConsortium、shajoezhu、Roche、swhume、AstraZeneca、atorus-research 和 openpharma。关键词、关注账号及数量上限可在 [collector/radar_config.json](collector/radar_config.json) 中调整。

## 每日更新与部署

GitHub Actions 的备用定时配置为每天 **北京时间早上 08:00**（UTC 00:00）。原生 `schedule` 触发可能延迟数小时，不能据此承诺准点启动。外部云定时服务可以通过 `workflow_dispatch` 接口主动触发，绕过 GitHub 的定时事件队列；执行节点排队、网络故障与采集耗时仍可能影响启动或完成时间。

**独立触发器接入状态：仓库接口与每日去重已准备，外部云服务尚待账号配置并验证；当前不能视为已启用。** 接入方法见 [独立定时触发器](docs/scheduler.md)。

外部定时调用设置 `refresh=true`、`daily_refresh=true`。原生定时任务也自动进入同一个每日检查：只有线上临床情报和开源仓库均已在当天北京时间 08:00 后成功采集并发布，才跳过重复采集。只完成一个模块、上次失败、昨天的数据或清晨手动更新均不会阻止今日重试。读取状态失败时继续刷新，不因检查故障漏掉更新。来源覆盖受限但整体采集成功的状态不触发无限重试，逐站问题仍保留在采集说明。

整个工作流共用并发锁，刷新与发布串行执行；触发器可以在 08:10、08:25 补发，已成功发布时自动跳过。流程为读取最近状态、采集数据、验证页面、保存状态、部署 GitHub Pages。

工作流在 [.github/workflows/dashboard.yml](.github/workflows/dashboard.yml)。维护者可以在 Actions 页面手动运行 **Refresh and publish dashboard**，默认勾选 `Collect fresh data before publishing`。取消勾选仅用于已有当日独立快照的发布；日期与来源验证不通过时不会部署。采集程序整体失败时，本轮不会替换现有站点；单站失败允许其他站继续更新，并在页面显示失败状态。

跨运行的去重状态、独立分析缓存和最近数据保存在 Actions 缓存中。缓存失效时重新访问官网采集，不恢复第三方汇总。Pages 发布文件使用明确清单，仅包含页面与展示用 JSON。

## 配置

1. 将仓库的 Settings → Pages → Source 设为 **GitHub Actions**。
2. 在 Settings → Secrets and variables → Actions 中创建 **DEEPSEEK_API_KEY**。
3. 工作流使用 GitHub 提供的 **GITHUB_TOKEN** 访问公开仓库数据，无需额外提交个人 Token。
4. 在 Actions 页面手动启动一次工作流，确认更新和部署完成。

DeepSeek Key 通过环境变量传给 `refresh.py`，仅在云端采集步骤中可用。凭据应存入 Actions Secrets，更新密钥也在仓库设置中完成。

## 本地运行

要求 macOS 或 Linux、Python 3.10+。页面不依赖构建工具；采集的 HTML 解析依赖在 requirements.txt 中固定。GitHub CLI 可用于本地凭据读取。

```bash
git clone https://github.com/allensrj/biometrics-desk.git
cd biometrics-desk
python3 -m pip install -r requirements.txt
python3 serve.py
```

默认在浏览器打开 `http://127.0.0.1:8765/`，终端按 Ctrl+C 停止。macOS 也可双击 `启动看板.command`。

手动采集需要有效的 GitHub 和 DeepSeek 凭据。可设置 `GITHUB_TOKEN`、`DEEPSEEK_API_KEY` 环境变量；本机已登录 `gh` 时，脚本可读取 GitHub CLI 凭据。准备好凭据后运行：

```bash
python3 refresh.py
```

运行状态默认位于用户目录 `Library/Application Support/ClinicalRadar`，可通过 `RADAR_STATE_DIR` 覆盖。该目录应放在页面发布目录之外。

## 项目来源与许可

本项目参考 [EmilyLiu312/clinical-biometrics-radar](https://github.com/EmilyLiu312/clinical-biometrics-radar) 的看板思路与来源选择，并融合原有药企开源仓库雷达。临床采集与分析已改为本项目独立实现，运行时不依赖参考仓库的数据或更新。历史改造所涉及的原始版权声明继续保留。

本项目采用 [MIT License](LICENSE)。上游 MIT 许可及版权声明保留在 [UPSTREAM-LICENSE](UPSTREAM-LICENSE)。法规、标准文件和第三方项目内容的权利归各自来源所有。

更多交流可在微信搜索公众号 **药企SP程序员Allen**。
