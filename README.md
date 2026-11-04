# 临床统计编程信息看板 · Biometrics Desk

[打开在线看板](https://allensrj.github.io/biometrics-desk/) · [每日更新记录](https://github.com/allensrj/biometrics-desk/actions/workflows/dashboard.yml)

面向药企临床统计编程人员的信息看板，把法规、数据标准、行业动态和相关开源工具放在一个页面里。使用者可以快速浏览近期更新，筛选重要情报，查看未来事项，再通过原文链接核实细节。

页面包含「临床情报」和「开源仓库」两个部分。高、中、低等级统一使用灰红、灰黄、灰绿色标记，并保留文字说明。搜索、主题筛选和首页数字均可直接操作。未来 30 天的事项在时间轴上展示，悬停可以预览，点击事项可以定位到看板中的对应条目。

## 临床情报

收录最近 **90 个北京时间自然日（含当天）**发布或由官网修订的内容，按发布日期从新到旧排序。首次采集日期与文件发布日期分别记录。较早发布但仍有未来截止日的通知保留在近期事项中。

| 来源 | 关注内容 | 获取方式 |
| --- | --- | --- |
| CDISC、CDE、ICH、FDA、PHUSE、美国联邦公报 | 法规指南、临床数据标准、统计编程行业动态、会议和征求意见 | 同步 [Clinical Biometrics Radar](https://github.com/EmilyLiu312/clinical-biometrics-radar) 的已发布汇总，再按日期窗口筛选 |
| [PMDA](https://www.pmda.go.jp/english/review-services/reviews/0002.html) | 日本电子研究数据标准目录、验证规则 | 直接解析官方资料索引的版本和日期 |
| [NCI EVS](https://evs.nci.nih.gov/ftp1/CDISC/) | CDISC SDTM、ADaM 受控术语 | 直接读取术语发布文件的版本日期 |
| [EMA](https://www.ema.europa.eu/en/about-us/how-we-work/data-regulation-big-data-other-sources/use-clinical-study-data-medicine-evaluation) | 临床研究数据试点说明、申请人问答和配套资料 | 直接解析官方索引的文件日期与链接 |

官网索引提供的是特定资料范围。每日检查可以发现该范围内的新版本，实际收录量取决于来源是否有近期发布。来源失败时会保留最近成功的数据。情报的重要度、摘要和对统计编程的影响随条目展示，阅读原文可核对内容和适用范围。

## 开源仓库

通过 GitHub API 检索最近 **5 个北京时间自然日（含当天）**创建的相关公开仓库。关键词分两级，第一类围绕 CDISC、SDTM、ADaMIG 等专业标准，另一类如 SAS、ADaM、TFL 需要结合临床与医药上下文核验。候选仓库进一步读取 README，由 DeepSeek 生成中文摘要与高、中、低相关性判读，判读失败时标为「待确认」并留待重试。

已收录仓库会去重，对内容较少或尚未完成判读的候选做七天回看。列表按相关性优先排列，同一档内按仓库创建时间倒序排列。GitHub 搜索结果与 README 请求数量设有上限，因此每次收录有数量边界。

还会检查关注账号中近期有推送的相关公开项目，单列正式 Release。当前范围包括 pharmaverse、cdisc-org、phuse-org、RConsortium、shajoezhu、Roche、swhume、AstraZeneca、atorus-research 和 openpharma。关键词、关注账号及数量上限可在 [collector/radar_config.json](collector/radar_config.json) 中调整。

## 每日更新与部署

GitHub Actions 每天 **北京时间早上 08:00**（UTC 00:00）计划启动采集，流程为读取最近状态、采集数据、验证页面、保存状态、部署 GitHub Pages。Actions 排队和来源响应速度会影响实际完成时间。

工作流在 [.github/workflows/dashboard.yml](.github/workflows/dashboard.yml)。维护者可以在 Actions 页面手动运行 **Refresh and publish dashboard**，默认勾选 `Collect fresh data before publishing`。取消勾选会直接发布仓库随代码保存的快照。采集步骤失败时，本轮不会替换现有站点。

跨运行的去重状态和最近数据保存在 Actions 缓存中。缓存失效时从仓库快照重新采集。Pages 发布文件使用明确清单，仅包含页面与展示用 JSON。

## 配置

1. 将仓库的 Settings → Pages → Source 设为 **GitHub Actions**。
2. 在 Settings → Secrets and variables → Actions 中创建 **DEEPSEEK_API_KEY**。
3. 工作流使用 GitHub 提供的 **GITHUB_TOKEN** 访问公开仓库数据，无需额外提交个人 Token。
4. 在 Actions 页面手动启动一次工作流，确认更新和部署完成。

DeepSeek Key 通过环境变量传给 `refresh.py`，仅在云端采集步骤中可用。凭据应存入 Actions Secrets，更新密钥也在仓库设置中完成。

## 本地运行

要求 macOS 或 Linux、Python 3.10+。页面和采集脚本使用 Python 标准库。GitHub CLI 可用于本地凭据读取。

```bash
git clone https://github.com/allensrj/biometrics-desk.git
cd biometrics-desk
python3 serve.py
```

默认在浏览器打开 `http://127.0.0.1:8765/`，终端按 Ctrl+C 停止。macOS 也可双击 `启动看板.command`。

手动采集需要有效的 GitHub 和 DeepSeek 凭据。可设置 `GITHUB_TOKEN`、`DEEPSEEK_API_KEY` 环境变量；本机已登录 `gh` 时，脚本可读取 GitHub CLI 凭据。准备好凭据后运行：

```bash
python3 refresh.py
```

运行状态默认位于用户目录 `Library/Application Support/ClinicalRadar`，可通过 `RADAR_STATE_DIR` 覆盖。该目录应放在页面发布目录之外。

## 项目来源与许可

本项目基于 [EmilyLiu312/clinical-biometrics-radar](https://github.com/EmilyLiu312/clinical-biometrics-radar) 的临床情报看板改造，并融合了原有药企开源仓库雷达的采集逻辑，重新整理了页面布局、筛选、事项定位和自动部署流程。

本项目采用 [MIT License](LICENSE)。上游 MIT 许可及版权声明保留在 [UPSTREAM-LICENSE](UPSTREAM-LICENSE)。法规、标准文件和第三方项目内容的权利归各自来源所有。

更多交流可在微信搜索公众号 **药企SP程序员Allen**。
