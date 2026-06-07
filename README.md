# flashnovel

面向长篇小说/剧本连续创作的 Agent Runtime 与上下文记忆编排系统。

## 核心目标

- 章节级状态机：`context -> plan -> draft -> extract -> check -> review -> rewrite -> commit -> checkpoint`
- SQLite + 文件 Artifact Store：结构化状态进 SQLite，大文本进文件
- 四层记忆模型：Artifact / Canon / Episodic / Continuity
- Context Builder：按需装配故事设定、近期摘要、时间线、人物关系、伏笔、状态变化和评审提醒
- 5 章 checkpoint：每批 5 章暂停人工确认，确认后续跑
- SSE 事件流：输出节点、工具、LLM delta、错误和 checkpoint
- 断点恢复：run/checkpoint/pending state 持久化

## Web 端演示

工作台可创建故事并启动章节生成，实时展示 Agent 工作流节点、运行事件和生成状态。

![FlashNovel Web 工作台运行事件](docs/images/flashnovel-run-events.png)

章节提交后，可在工作台中查看生成正文、Artifact 以及结构化记忆视图。

![FlashNovel Web 工作台记忆视图](docs/images/flashnovel-memory-view.png)

## 本地运行

后端会自动读取项目根目录的 `.env`。首次运行前，复制 `.env.example` 为 `.env`，并把 `FLASHNOVEL_API_KEY` 填成你的真实 key；如果不想安装本项目，也可以继续在当前终端设置 `PYTHONPATH`。

```powershell
git clone https://github.com/CuSO41108/flashnovel.git
cd flashnovel
Copy-Item .env.example .env
$env:PYTHONPATH="$PWD\backend"
python -m app.api.app
```

默认服务地址：`http://127.0.0.1:8010`

前端工作台：

```powershell
cd frontend
npm install
npm run dev
```

默认前端地址：`http://127.0.0.1:5173`

## 项目结构

| 路径 | 作用 |
| --- | --- |
| `backend/app/api` | FastAPI 应用、依赖注入与 HTTP 路由 |
| `backend/app/runtime` | Run 创建、worker、恢复、事件与运行生命周期 |
| `backend/app/graph` | 章节级 LangGraph / fallback 工作流节点 |
| `backend/app/tools` | context / plan / draft / extract / check / review / rewrite / commit 工具链 |
| `backend/app/memory` | SQLite schema、Artifact Store、上下文构建与记忆视图 |
| `backend/app/llm` | OpenAI-compatible LLM 客户端与 prompts |
| `backend/tests` | 后端 smoke、环境加载、恢复与预算测试 |
| `frontend/src` | React 工作台、API 封装、SSE 事件处理与前端测试 |
| `docs` | 架构说明 |

## 验证

```powershell
$env:PYTHONPATH="$PWD\backend"
python -m pytest

cd frontend
npm test
npm run build
```

## API 预览

```text
GET  /health
POST /stories
GET  /stories
GET  /stories/{story_id}
GET  /workspaces/{story_id}
GET  /workspaces/{story_id}/memory
GET  /workspaces/{story_id}/artifacts
POST /runs
GET  /runs
GET  /runs/{run_id}
POST /runs/{run_id}/pause
POST /runs/{run_id}/resume
POST /runs/{run_id}/cancel
POST /runs/{run_id}/confirm
GET  /runs/{run_id}/events
GET  /runs/{run_id}/events/stream
GET  /stories/{story_id}/chapters/{chapter}
```

## 设计摘要

`flashnovel` 将长篇创作拆成可观察、可恢复的 Agent 节点，并把每章产物沉淀为结构化记忆。下一章生成时，系统不会简单塞入全部历史正文，而是读取章节摘要、时间线、人物关系、伏笔账本、状态变化和评审提醒，构建受 token budget 约束的上下文包。

## 阶段目标

| 阶段 | 定位 |
| --- | --- |
| V1 flashnovel | 单用户 / 本地 / 轻量工作台，Python 同时承担后端和 Agent Runtime |
| V2 平台化 | Java 承担租户、用户、权限、审计、平台元数据、统一 API；Python 退到 Internal Agent Runtime |
