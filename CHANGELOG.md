# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 发版流程：改 `backend/app/core/config.py` 的 `app_version` → 在本文件顶部新增一段
> → `git tag -a vX.Y.Z` → `git push origin vX.Y.Z`。
> CI 会校验本文件确实包含该版本段落，缺失则发版失败。

## [1.0.0] - 2026-10-15

### 新增

- 企业级 RAG 知识库智能体平台首发：三类知识库（向量/图文/外部）、混合检索与引用溯源
- 智能体平台：ReAct 工具循环、技能与技能市场、行为模式、工作流 DAG 编排
- 外部渠道与客服：QQ/微信/企业微信/飞书接入、工单 SLA、话术库、渠道身份绑定
- 办公与自动化：智能录单、办公文档生成（docx/xlsx/pdf/pptx）、待办日程、审批中心、定时任务
- 平台能力：MCP 客户端、模型管理、RBAC + 文档级 ACL、审计日志、用量统计、单点登录
- 个人邮件管理（IMAP 收 + SMTP 发）与邮件入库打通
- 桌面版（Electron）、Docker 镜像与 GitHub Actions 自动构建发布
