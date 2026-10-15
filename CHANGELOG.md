# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 发版流程：改 `backend/app/core/config.py` 的 `app_version` → 把本文件顶部
> `[Unreleased]` 段改名为 `## [X.Y.Z] - 日期` → `git tag -a vX.Y.Z` → `git push origin vX.Y.Z`。
> CI 会校验本文件确实包含该版本段落，缺失则发版失败。

## [Unreleased]

### 新增

- **应用内检查更新**：侧边栏显示当前版本，可检查 GitHub Release 是否有新版本
- **桌面版在线更新**：下载 → sha256 校验 → 换盘 → 自动重启（绿色版免安装）
- **更新日志滚动条**：顶部 header 下方横向滚动，所有登录用户可见，可展开多版本历史
- **更新内容托管**：仓库根 `CHANGELOG.md` 为源，Release 正文由 CI 自动提取

### 修复

- **PDF 中文乱码**：容器/GitHub Runner 缺中文字体时，生成的 PDF 中文变占位符；
  现自动扫描系统字体并支持 `RAG_PDF_FONT` 指定，缺字体时显式告警
- **Docker 更新指引**：容器无法替换自身镜像，改为提示在宿主机执行
  `docker compose pull && docker compose up -d`
- 非管理员不再请求管理员专属的更新接口（此前每次加载都刷 401）

## [1.0.0] - 2026-10-15

### 新增

- 企业级 RAG 知识库智能体平台首发：三类知识库（向量/图文/外部）、混合检索与引用溯源
- 智能体平台：ReAct 工具循环、技能与技能市场、行为模式、工作流 DAG 编排
- 外部渠道与客服：QQ/微信/企业微信/飞书接入、工单 SLA、话术库、渠道身份绑定
- 办公与自动化：智能录单、办公文档生成（docx/xlsx/pdf/pptx）、待办日程、审批中心、定时任务
- 平台能力：MCP 客户端、模型管理、RBAC + 文档级 ACL、审计日志、用量统计、单点登录
- 个人邮件管理（IMAP 收 + SMTP 发）与邮件入库打通
- 桌面版（Electron）、Docker 镜像与 GitHub Actions 自动构建发布
