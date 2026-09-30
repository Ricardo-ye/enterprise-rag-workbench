# Enterprise RAG 运维手册

## 工作台入口

- `GET /` 或 `GET /ui`：可视化管理与问答工作台
- `GET /assets/*`：随应用打包的 CSS、JavaScript 和图标

工作台入口及静态资源保持公开，以便加载登录前界面；所有非健康业务 API 仍遵循 `X-API-Key` 中间件。API Key 只写入标签页级 `sessionStorage`，不会写入服务器、Cookie 或持久化浏览器存储。

## 启动前检查

生产环境必须设置：

- `RAG_ENVIRONMENT=production`
- 长度至少 16 字符的 `RAG_API_KEY`
- 不含 `*` 的 `RAG_TRUSTED_HOSTS`
- 可访问的模型提供商配置
- 绝对且持久化的 `RAG_DATABASE_PATH`

生产模式默认关闭 Swagger 和 ReDoc。除健康检查外，请求必须携带 `X-API-Key`。

## 启动与停止

```powershell
docker compose up --build -d
docker compose ps
docker compose logs -f api
docker compose down
```

Compose 使用非 root 用户、只读根文件系统、全量 capability drop、`no-new-privileges` 和独立数据卷。SQLite 数据保存在 `rag-data` 卷中；`docker compose down` 不会删除该卷，只有显式添加 `--volumes` 才会删除。

当前开发主机没有 Docker 时，可运行：

```powershell
uv sync
uv run uvicorn enterprise_rag.main:app --host 127.0.0.1 --port 8000
```

## 探针和指标

- `/health/live`：仅检查进程存活，不依赖数据库或模型网络
- `/health/ready`：检查 SQLite 可连接且核心表完整，并报告模型提供商配置
- `/metrics`：Prometheus 文本指标
- `/api/v1/observability/slo`：当前进程生命周期内的可用率、P95 延迟和答案成功率
- `/api/v1/rag/quality/summary`：持久化答案审核结果汇总

设置了 API Key 时，指标与 SLO 接口也必须携带 `X-API-Key`；健康探针不需要。

进程重启会清空进程内指标和 SLO 窗口，但不会清除 SQLite 中的答案质量记录。生产环境应让 Prometheus 定期抓取并长期保存指标。

## 数据完整性与备份

服务统一启用 SQLite WAL、外键、忙等待和可配置同步级别。容器默认使用 `RAG_SQLITE_SYNCHRONOUS=FULL`；本地默认 `NORMAL`。启动时所有表创建完成后才提交当前 schema 版本，就绪探针同时校验完整性、核心表和版本。

检查运行库：

```powershell
uv run enterprise-rag storage --database data/enterprise_rag.db verify
```

创建不会覆盖旧文件的一致在线备份：

```powershell
uv run enterprise-rag storage --database data/enterprise_rag.db backup `
  --output backups/enterprise-rag-20260927.db
```

同目录会生成 `.db.manifest.json`，其中包含 SHA-256、文件大小和 schema 版本。恢复前应比对摘要，并先对候选文件运行 `storage verify`。恢复属于有状态变更，应先停止写流量、保留当前库，再由运维人员显式切换文件；命令不会自动覆盖或恢复数据库。

## 端到端回归

服务启动且知识已导入后执行：

```powershell
uv run enterprise-rag evaluate `
  --dataset evals/sample-answers.json `
  --output outputs/evaluation.json `
  --base-url http://127.0.0.1:8000
```

启用 API Key 时增加 `--api-key`，或设置 `RAG_API_KEY`。报告包含回答成功率、拒答准确率、引用来源召回率、平均置信度、修复率、人工转接率及 P50/P95 延迟。

## 常见故障

### 就绪探针返回 503

检查响应中的 `components.database`。`missing_tables` 表示数据库初始化不完整，`schema_version` 表示应用与库版本不一致，`error:*` 通常表示路径、权限、磁盘或 SQLite 文件损坏。确认容器数据卷对 UID 10001 可写，再运行 `storage verify` 获取详细结果。

### 大量 `insufficient_evidence`

确认文档已入库，查看五路检索状态和精排得分。默认哈希嵌入器只适合离线演示；生产环境应替换为正式向量模型，并用固定评测集校准 `RAG_GENERATION_MIN_EVIDENCE_SCORE`。

### 大量 `needs_human`

查看答案响应中的两次 `attempts` 和门控原因，再检查 `/api/v1/rag/quality/summary`。不要简单降低阈值；优先修复检索证据、提示词、模型 JSON 格式或风险话术。

### 请求返回 429

当前限流是单进程、按客户端地址的基础保护。检查 `Retry-After`，并调整 `RAG_RATE_LIMIT_REQUESTS_PER_MINUTE`。多副本生产部署应改用网关或 Redis 分布式限流。

## 已知生产边界

- 当前已具备 SQLite 统一连接策略、schema 版本、完整性检查和一致在线备份，但 SQLite 仍只适合单实例和中小规模部署；多副本写入应迁移到 PostgreSQL，并将向量检索迁移到 pgvector、OpenSearch 或专用向量库。
- API Key 是基础服务认证，不提供用户级 RBAC 或租户数据隔离。真实企业接入应在网关验证身份，并把租户标识贯穿文档、FAQ、任务和审计表。
- 内存限流、熔断器和指标不跨进程共享。
- SearXNG、OpenAI-compatible 和 Ollama 的可用性不由就绪探针主动调用，避免外部故障导致实例反复重启；它们的失败会在请求指标和路由状态中暴露。
