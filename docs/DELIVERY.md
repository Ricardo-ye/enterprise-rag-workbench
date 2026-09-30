# Enterprise RAG 最终交付说明

## 可交互成果

根路径 `/` 和 `/ui` 提供可直接体验的企业 RAG 工作台。它通过同源 API 完成问答、证据检查、知识治理、检索验证和运行观测，不依赖 Node.js 或额外前端服务。生产环境启用 API Key 后，可在连接设置中仅为当前浏览器会话配置密钥。

## 交付范围

当前版本已经形成一条可运行的企业问答主链路：

1. Markdown、TXT、PDF、FAQ 和 KG 知识入库及版本治理。
2. 输入安全、ToC/ToB、领域、子意图和任务/问答路由。
3. 有状态 Task Flow、槽位收集及模拟业务动作。
4. FAQ 精确通道、FAQ/KG 双门控及 RAG 降级。
5. 语义、关键词、Web、KG、FAQ 五路检索，RRF 融合和精排。
6. 证据约束生成、引用检查、事实/合规/相关/完整性审核。
7. 一次自动修复、证据不足拒答和二次失败转人工。
8. SSE、质量审计记录、离线评测、Prometheus 指标和 SLO。
9. API Key、基础限流、Trusted Host、真实就绪检查和加固容器配置。
10. SQLite 统一连接策略、schema 版本、完整性检查和带摘要的一致在线备份。

## 最短复现路径

```powershell
uv sync
Copy-Item .env.example .env
uv run uvicorn enterprise_rag.main:app --host 127.0.0.1 --port 8000
```

在另一个终端运行最终验收：

```powershell
uv run enterprise-rag accept `
  --base-url http://127.0.0.1:8000 `
  --output outputs/final-acceptance.json
```

命令会幂等导入专用验收知识，然后验证平台、安全、路由、任务、KBQA、RAG、质量门控、流式输出、评测和观测链路。任一用例失败都会返回非零退出码。

## 主要扩展接口

- `ModelProvider`：替换 OpenAI-compatible、Ollama 或企业内部模型网关。
- `EmbeddingProvider`：替换默认哈希嵌入。
- `Retriever`：接入向量库、OpenSearch、数据库或受控互联网搜索。
- `Reranker`：接入 Cross-Encoder 或内部排序服务。
- `ActionAdapter`：接入真实 CRM、预约、理赔和工单系统。
- `SQLiteDatabase`：统一连接、schema 生命周期、健康检查与在线备份；下一阶段可在仓储边界迁移到 PostgreSQL、pgvector、OpenSearch 或 Neo4j。

## 上线前仍需完成

以下项目依赖目标组织、基础设施或真实数据，不能由本地演示替代：

- 使用正式向量模型、生成模型和验证集重新校准全部阈值。
- 在 API 网关接入 OIDC/mTLS、用户 RBAC、租户标识和审计主体。
- 将所有知识、任务和质量数据按租户强制隔离。
- 多副本部署前，将 SQLite 仓储迁移到 PostgreSQL/pgvector，并将内存限流、指标和熔断状态迁移到共享组件。
- 对真实业务 Action 做鉴权、确认、幂等、补偿和灾备演练。
- 配置密钥管理、日志脱敏、数据保留期、备份恢复和删除流程。
- 在目标容器平台完成并发、长稳、故障注入和容量评估。
- 使用真实 OpenAI/Ollama/SearXNG 连接执行供应商级验收。

## 交付物索引

- `README.md`：开发、API 和配置说明。
- `docs/OPERATIONS.md`：部署、探针、监控和故障排查。
- `docs/DELIVERY.md`：交付边界、扩展点和上线前任务。
- `evals/sample-answers.json`：答案评测样例。
- `outputs/final-acceptance.json`：最终验收报告。
- `tests/`：分层单元、集成及端到端回归。
