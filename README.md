# Biometrics Desk · 临床编程观察台

[打开在线工作台](https://allensrj.github.io/biometrics-desk/)

面向药企临床统计编程团队的每日看板。临床情报按发布日期倒序展示近 90 个北京时间自然日的法规、数据标准和行业动态，支持按主题与重要度筛选。未来 30 天的会议与反馈截止日可以在时间轴上查看。

开源仓库板块检索最近五天新建的相关公开仓库，由 DeepSeek 生成中文判读，并单独列出关注账号的项目正式发布。仓库按相关性排序，同档内最新创建的排在前面。

## 数据与更新

临床汇总来自 [Clinical Biometrics Radar](https://github.com/EmilyLiu312/clinical-biometrics-radar)，许可见 UPSTREAM-LICENSE。看板也直接检查 PMDA 研究数据标准目录与验证规则、NCI EVS 受控术语和 EMA 临床数据试点资料。每项情报可追溯到原文。来源范围、采集时间和 GitHub 搜索上限可在页面的同步记录中查看。

GitHub Actions 每天北京时间 08:00 计划启动采集，完成后部署至 GitHub Pages。实际时间取决于 Actions 排队与采集耗时。采集失败的工作流不会覆盖当前站点。维护者可以在 Actions 中手动运行 **Refresh and publish dashboard**。日常刷新请勾选 Collect fresh data；取消勾选会直接发布仓库中随代码保存的快照。

## 配置与本地运行

使用 Actions 部署时，将 Pages 的构建来源设为 GitHub Actions，在仓库的 Actions Secrets 中设置 DEEPSEEK_API_KEY。工作流自带的 GITHUB_TOKEN 读取 GitHub 公开数据。密钥只传给采集步骤，Pages 仅接收页面及展示用 JSON。不要把凭据写入源代码或数据文件。缓存只保存已收录仓库状态与最近的数据快照，缓存失效时会从仓库快照重新采集。

本地预览可运行 `python3 serve.py`，macOS 也可双击启动脚本。本地刷新运行 `python3 refresh.py`，需要 Python 3.10+、GitHub 凭据和 DeepSeek Key，可通过环境变量注入。账号及关键词在 collector/radar_config.json 中维护。
