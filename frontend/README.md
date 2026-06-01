# FlashNovel Frontend

轻量 Vite React 工作台，直接对接 `http://127.0.0.1:8010` 的 FastAPI 后端。

```powershell
cd flashnovel/frontend
npm install
npm run dev
```

配置：

- `frontend/.env`：本地前端配置，默认 `VITE_API_BASE_URL=http://127.0.0.1:8010`
- `frontend/.env.example`：可提交的示例配置

真实 LLM key 不要放在前端，只放项目根目录的 `.env`，由后端读取。
