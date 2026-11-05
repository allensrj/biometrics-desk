# 独立定时触发器

状态：GitHub 接口与每日去重已接入，外部云定时服务待账号配置及实际触发验证。不能仅凭仓库配置声称独立定时已上线。

## 云定时服务接入

建议使用 [cron-job.org](https://cron-job.org/en/) 的 HTTPS 定时请求，也可使用自己的 Linux 定时器或 Cloudflare Worker 调用同一接口。网站和采集仍托管在 GitHub，无需电脑常开。外部触发绕过 GitHub 的 schedule 队列，不承诺 GitHub 执行节点秒级启动。

1. 在 GitHub 创建专用 fine-grained token，Resource owner 为 allensrj，仅选择 biometrics-desk 仓库，Repository permissions 仅增加 **Actions: Read and write**（Metadata 为默认读取）。设置有效期并安排到期前轮换，不复用个人全权限 Token。
2. 登录云定时服务，建立任务，时区 **Asia/Shanghai**，每天 **08:00、08:10、08:25** 调用下列接口。08:00 是主触发；后两次补发会先检查线上是否已成功更新，已完成则跳过。
3. HTTP 方法 **POST**，URL：

   `https://api.github.com/repos/allensrj/biometrics-desk/actions/workflows/dashboard.yml/dispatches`

4. 请求头（仅在云服务的私有配置填写凭据，禁止提交真实值）：

   ```text
   Accept: application/vnd.github+json
   Content-Type: application/json
   Authorization: Bearer <专用 GitHub token>
   X-GitHub-Api-Version: 2026-03-10
   ```

5. 请求体：

   ```json
   {"ref":"main","inputs":{"refresh":true,"daily_refresh":true}}
   ```

6. 使用云服务的测试执行检查接口返回，并在 [Actions](https://github.com/allensrj/biometrics-desk/actions/workflows/dashboard.yml) 确认新运行出现、采集与部署均成功。接口返回成功只表示触发请求已接收，不等于页面已更新。再次调用应跳过 build/deploy，Actions 摘要显示当日已更新；08:00 前的测试不会满足每日去重条件。
7. 核对云服务下一次执行时间为北京时间 08:00，并检查首个实际定时运行记录。需要失败邮件提醒时，在云服务中明确配置接收渠道；该提醒只能证明 HTTP 触发失败，采集/部署失败仍需查看 GitHub Actions 通知。

DeepSeek 密钥始终只保留在 GitHub Actions Secrets，外部调度器不需要接触它。外部服务只保管专用 GitHub Token。该 Token 的 Actions 写权限也允许操作本仓库其他工作流，GitHub 无法将此 PAT 权限进一步限制到一个 workflow 文件；可随时在 GitHub 撤销。

## 去重与恢复

- workflow 级别 `dashboard-pages` 并发组，`cancel-in-progress: false`，不取消正在执行的刷新。GitHub 对同一组只保留有限的待运行实例；补发并非持久任务队列。
- `scripts/refresh_gate.py` 检查已部署页面的 `refresh-status.json`，只有两个模块均 `ok=true`，且采集时间在当天 08:00 到当前时刻之间，才判定今日刷新完成。
- 判断基于线上发布版本，因此“采集成功但部署失败”不会阻止补发重试。请求加缓存区分参数；CDN 短暂未同步可能导致多采集一次，但不会把昨天数据误认作今天。
- 临床单站访问受限属于覆盖限制，已在看板说明；不等同整个模块失败。
- 原 GitHub schedule 保留作另一条触发路径，晚到时同样检查并跳过已更新数据。
- 维护者手动运行默认 `daily_refresh=false`，可主动强制刷新；仅发布快照的 `refresh=false` 操作不受每日去重阻挡，仍须通过原有日期与来源验证。

## 运维检查

每天看两个时间：云服务实际发出请求的时间，以及 GitHub build/deploy 完成时间。08:00 发出请求不代表08:00页面已完成更新。任何单一云服务均可能故障；本方案以外部主触发、补发和 GitHub 备用降低漏运行风险。

依据：[GitHub workflow_dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)、[cron-job.org API](https://docs.cron-job.org/rest-api.html)。
