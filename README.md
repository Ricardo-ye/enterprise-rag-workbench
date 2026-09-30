# Enterprise RAG Workbench

[中文](#中文) | [English](#english)

## English

### Overview

Enterprise RAG Workbench is a runnable, production-oriented reference implementation for enterprise Retrieval-Augmented Generation (RAG). It unifies knowledge ingestion, layered routing, task flows, FAQ and knowledge-graph QA, multi-channel retrieval, evidence-grounded generation, quality gates, observability, and a visual workbench in one service.

The default `mock` model and `hashing-v1` embedder are deterministic and offline, so the complete workflow can be explored without an API key or an external model service. Production deployments can switch to OpenAI-compatible APIs, Ollama, SearXNG, and Cross-Encoder adapters.

### Features

- Knowledge lifecycle: Markdown, UTF-8 text, and PDF ingestion; heading-aware chunking; SHA-256 idempotency and cross-source deduplication; versions, soft deletion, FAQs, and knowledge-graph triples.
- Layered orchestration: safety checks, consumer/business classification, domain and sub-intent recognition, and routing to `reject`, `chitchat`, `task_flow`, `kbqa`, or `rag`.
- Retrieval and QA: parallel semantic, lexical, web, knowledge-graph, and FAQ retrieval; RRF fusion, deduplication, pluggable reranking, and source-numbered evidence with citations.
- Controlled generation: evidence-grounded prompting, citation/fact validation, compliance auditing, low-confidence refusal, one automated repair attempt, and human handoff.
- Operational foundations: SQLite readiness and backup, API-key protection, basic rate limiting, trusted hosts, Prometheus metrics, SLOs, and answer-quality records.
- Visual workbench: responsive built-in UI for chat, multi-turn sessions, document upload, FAQ/KG management, retrieval debugging, feedback states, and keyboard interaction.
- Quality assurance: unit, integration, security, UI, end-to-end acceptance, plus generalization and stability datasets.

### Installation

**Prerequisites:** Python 3.12+ and [uv](https://docs.astral.sh/uv/). Docker is optional.

```bash
git clone https://github.com/Ricardo-ye/enterprise-rag-workbench.git
cd enterprise-rag-workbench
uv sync
```

Create local configuration and start the server:

```powershell
Copy-Item .env.example .env
uv run uvicorn enterprise_rag.main:app --host 127.0.0.1 --port 8000
```

Open the workbench at <http://127.0.0.1:8000/> (or `/ui`), the Swagger API at <http://127.0.0.1:8000/docs>, and the health probes at `/health/live` and `/health/ready`.

### Usage

1. Ask a question in the workbench and inspect the answer, citations, route decision, and retrieval state. Upload documents or import FAQ/KG triples from the management views, then return to chat to verify retrieval.
2. Ingest a document through `POST /api/v1/knowledge/documents/ingest`; use `POST /api/v1/rag/retrieve` to inspect evidence, or `POST /api/v1/rag/answer` for retrieve → generate → audit.
3. Use `POST /api/v1/assistant/respond` for the unified QA/task-flow entry point. `POST /api/v1/rag/answer/stream` streams only the final, audited answer via SSE.
4. To use a real model, set `RAG_MODEL_PROVIDER`, endpoint, model, and secret in the untracked `.env` file. Never commit secrets.

Run the quality checks and acceptance test:

```bash
uv run ruff check .
uv run mypy
uv run pytest
uv run enterprise-rag accept --base-url http://127.0.0.1:8000 --output outputs/final-acceptance.json
```

Run `docker compose up --build` for the optional container deployment. See the [Interactive Demo](docs/demo.md), [Operations guide](docs/OPERATIONS.md), [Contributing guide](CONTRIBUTING.md), and [Security policy](SECURITY.md) for deployment, contribution, and reporting details.

---

## 中文

面向企业问答场景的分层 RAG 参考实现。它把文档/FAQ/KG 入库、路由、Task Flow、
KBQA、五路检索、证据约束生成、质量门控、观测指标和可视化工作台放在同一个可运行
仓库里，适合做架构验证、二次开发和开源展示。

## 文档导航

- [运维手册](docs/OPERATIONS.md)：部署、探针、指标、备份和故障定位。
- [交互式演示](docs/demo.md)：问答、知识入库、检索对比和运行观测截图。
- [交付说明](docs/DELIVERY.md)：已交付能力、扩展点和上线前任务。
- [知识库文档](docs/KNOWLEDGE_BASE.md)：可上传到系统自身的结构化项目知识库文章。
- [开源发布指南](docs/OPEN_SOURCE_RELEASE.md)：GitHub 发布前的仓库整理清单。
- [贡献指南](CONTRIBUTING.md)：本地开发、质量检查和 PR 约定。
- [安全政策](SECURITY.md)：漏洞报告和安全范围说明。

## 仓库结构

```text
.
├── config/                  # 路由、安全词表和意图配置
├── docs/                    # 运维、交付、知识库和开源发布文档
├── evals/                   # 答案评测、通用性和稳定性数据集
├── src/enterprise_rag/      # FastAPI 服务、RAG 核心模块和内置工作台
├── tests/                   # 单元、集成、安全、UI 和端到端回归
├── .github/workflows/       # GitHub Actions CI
├── compose.yaml             # 容器化运行配置
├── pyproject.toml           # 依赖、脚本和质量工具配置
└── README.md
```

## 可视化工作台

服务启动后直接访问 `http://127.0.0.1:8000/` 或 `/ui`。工作台无需单独构建前端，随 FastAPI 一起运行，包含：

- 智能问答、连续对话、受众选择和任务补槽；
- 路由、安全判断、检索通道、耗时、引用与决策轨迹；
- 文档上传与停用、FAQ、知识图谱三元组和双路搜索；
- 服务健康、数据库状态、SLO 和答案质量记录；
- 会话级 API Key 配置，密钥仅保存在当前标签页的 `sessionStorage`。

界面支持桌面和移动端布局、键盘操作、加载/空/成功/错误状态以及减少动态效果偏好。

面向企业问答场景的分层 RAG 服务。当前已完成工程骨架和知识生命周期：

- Markdown、UTF-8 文本和可提取文字的 PDF 入库
- Markdown 标题感知分块及重叠窗口
- SHA-256 幂等导入、跨来源去重和文档版本记录
- SQLite FTS5 关键词索引和离线向量索引
- FAQ 批量导入、索引重建和文档软删除
- 安全检测、ToC/ToB 判断、领域与子意图分类
- 任务型/问答型分流、多轮任务继承和完整路由轨迹
- 多轮 Task Flow 槽位收集、会话持久化和动作适配器
- FAQ 精确直返、FAQ/KG 并行召回和双重质量门控
- 语义、关键词、Web、知识图谱和 FAQ 五路并行检索
- 路由级超时/熔断、RRF 融合、跨路去重和可切换精排器
- 带来源编号的证据上下文，以及 Recall@K、MRR、nDCG@K 评测
- 证据约束 LLM 生成、引用校验、幻觉/合规审计和一次自动修复
- 低置信度拒答、二次失败转人工，以及答案质量记录闭环
- 端到端答案评测、Prometheus 指标和进程级 SLO 判定
- API Key、基础限流、Trusted Host、真实数据库就绪检查和加固容器

服务已经具备从文档入库、分层路由、任务流/KBQA、五路检索到受控答案生成的完整主链路。

## 本地启动

需要 Python 3.12 和 `uv`：

```powershell
uv sync
Copy-Item .env.example .env
uv run uvicorn enterprise_rag.main:app --host 127.0.0.1 --port 8000
```

打开：

- API 文档：http://127.0.0.1:8000/docs
- 存活探针：http://127.0.0.1:8000/health/live
- 就绪探针：http://127.0.0.1:8000/health/ready

如设置 `RAG_API_KEY`，除健康探针外的请求都需要 `X-API-Key`：

```powershell
$headers = @{ "X-API-Key" = "your-service-key" }
Invoke-RestMethod http://127.0.0.1:8000/metrics -Headers $headers
```

默认模型提供商是 `mock`，不需要密钥。检查模型层：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/system/model/check `
  -ContentType application/json `
  -Body '{"prompt":"hello"}'
```

## 真实模型

OpenAI-compatible 服务：

```dotenv
RAG_MODEL_PROVIDER=openai
RAG_OPENAI_BASE_URL=https://api.openai.com/v1
RAG_OPENAI_API_KEY=replace-me
RAG_OPENAI_MODEL=gpt-4.1-mini
```

Ollama：

```dotenv
RAG_MODEL_PROVIDER=ollama
RAG_OLLAMA_BASE_URL=http://localhost:11434
RAG_OLLAMA_MODEL=qwen2.5:7b
```

## 知识库 API

导入 Markdown：

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/knowledge/documents/ingest `
  -F "file=@manual.md" `
  -F "source_uri=kb://vehicle/manual" `
  -F 'metadata_json={"department":"after-sales"}'
```

分别检查关键词索引和向量索引：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/knowledge/search `
  -ContentType application/json `
  -Body '{"query":"冬季续航为什么下降","limit":5}'
```

其他管理接口：

- `GET /api/v1/knowledge/documents`：列出文档和当前版本
- `DELETE /api/v1/knowledge/documents/{id}`：软删除文档及其活动索引
- `POST /api/v1/knowledge/faqs/import`：批量、幂等导入 FAQ
- `POST /api/v1/knowledge/indexes/rebuild`：根据当前文档版本重建索引

默认 `hashing-v1` 嵌入器无需联网，适合开发、验收和确定性测试。它保留了可替换的嵌入接口，但不等同于生产级语义模型；部署时应将该接口替换为组织选定的向量模型。精排器已提供离线启发式实现和可选 Cross-Encoder 适配器。

## 五路 RAG 检索

直接取得排序后的证据包：

```powershell
$body = @{ query = "星海 S7 的 CLTC 续航里程是多少" } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/rag/retrieve `
  -ContentType application/json `
  -Body $body
```

响应中的 `routes` 固定列出 `semantic`、`lexical`、`web`、`kg`、`faq`，每路都有耗时、命中数和状态。各路结果先用 RRF 融合，同一个文档分块被多路命中时合并并保留 `retrieval_routes`；不同分块仍保持独立。精排后生成带 `[1]` 编号、标题和 `Source` 的 `context` 与 `citations`，供答案生成使用。

默认 Web 路由关闭并明确返回 `skipped`。连接已有 SearXNG 后启用实时 Web 检索：

```dotenv
RAG_WEB_SEARCH_PROVIDER=searxng
RAG_SEARXNG_BASE_URL=http://localhost:8080
```

默认 `heuristic` 精排器完全离线且可重复。需要真实 Cross-Encoder 时，先在运行环境安装 `sentence-transformers`，再设置：

```dotenv
RAG_RERANKER_PROVIDER=cross_encoder
RAG_CROSS_ENCODER_MODEL=BAAI/bge-reranker-v2-m3
```

模型首次加载可能需要下载权重。缺少可选依赖时服务会在启动阶段返回明确的配置错误，不会静默退回启发式排序。

离线检索评测使用 `POST /api/v1/rag/evaluate`：

```json
{
  "k": 5,
  "cases": [
    {
      "query": "星海 S7 的续航",
      "relevant_source_ids": ["知识文档或 FAQ/KG 的 source_id"]
    }
  ]
}
```

返回逐用例与总体 `Recall@K`、`MRR`、`nDCG@K`。指标按 `source_id` 去重计算，避免同一文档的多个分块重复增加收益。

## 受控答案生成与质量门控

直接执行“检索 → 生成 → 审核 → 必要时修复”完整链路：

```powershell
$body = @{ query = "企业级 RAG 为什么需要质量门控" } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/rag/answer `
  -ContentType application/json `
  -Body $body
```

模型必须返回包含 `answer`、`relevance_score` 和 `accuracy_score` 的 JSON。系统随后执行以下确定性检查：

- 第一重门控：相关性和准确度自评分均达到阈值
- 引用门控：存在引用、编号真实、每条陈述在句末引用
- 事实门控：陈述与对应证据有足够文本支撑，数字必须出现在证据中
- 合规门控：拦截风险承诺和提示注入话术
- 完整性门控：拦截空答案和因 token 上限截断的答案
- 第二重门控：审核后的置信度仍达到阈值

第一次失败时，失败原因和原答案会进入一次低温修复请求；第二次仍失败则返回 `needs_human`，不会把未过审内容暴露给用户。没有达到最低相关度的证据时直接返回 `insufficient_evidence`，不调用模型猜测。

最终响应包含实际使用的引用、每次生成尝试、所有门控结果以及 `record_id`。质量记录持久化在 SQLite 的 `answer_quality_records` 表中；`GET /api/v1/rag/quality/summary` 返回通过、证据不足、人工兜底和修复数量汇总。

需要 SSE 时调用 `POST /api/v1/rag/answer/stream`。该接口先完成生成、引用检查和质量审核，再依次发送 `metadata`、`answer`、`done` 事件。它刻意不流式暴露尚未过审的模型 token，避免客户端收到之后又被审核器判定为幻觉或违规的内容。

默认 `mock` 提供商只用于确定性本地验收。切换 OpenAI-compatible 或 Ollama 后，使用完全相同的提示词、JSON 解析和质量门控，不会绕过审计。

## 评测、指标与 SLO

答案级评测 API 为 `POST /api/v1/rag/evaluate/answers`，支持为每条样本指定：

- 是否应该可回答
- 答案必须包含的短语
- 应引用的 `source_id`

结果包含回答成功率、拒答准确率、引用来源召回率、平均置信度、修复率、人工转接率以及 P50/P95 延迟。服务运行后可用一条命令读取数据集并生成 JSON 报告：

```powershell
uv run enterprise-rag evaluate `
  --dataset evals/sample-answers.json `
  --output outputs/evaluation.json `
  --base-url http://127.0.0.1:8000
```

运行时观测接口：

- `GET /metrics`：Prometheus 文本格式，包含 HTTP、答案状态和五路检索指标
- `GET /api/v1/observability/slo`：进程生命周期内的可用率、HTTP P95 和自动回答成功率
- `GET /api/v1/rag/quality/summary`：SQLite 中持久化的质量结果汇总

### 通用性与稳定性专项测试

`evals/generalization-stability.json` 按组记录典型场景、表达变化、输入边界、
异常与安全输入以及重复/并发稳定性用例。每个用例均包含输入、预期输出和判定标准。
对独立测试服务执行：

```powershell
uv run enterprise-rag generalize `
  --dataset evals/generalization-stability.json `
  --output outputs/generalization-stability-report.json `
  --base-url http://127.0.0.1:8000
```

报告保留每个用例的实际输出、耗时、错误、分组通过率和系统局限。默认即使发现通用性
不足也会完整生成报告；CI 需要失败退出时增加 `--strict`。

SLO 默认目标分别为 99% 可用率、2000ms HTTP P95 和 90% 自动回答成功率，可通过 `RAG_SLO_*` 配置调整。正确的“证据不足”拒答不计入自动回答成功率分母。

`/health/ready` 会实际连接 SQLite，并验证文档、分块、FAQ、任务、KG 和质量记录等核心表存在；失败返回 HTTP 503。模型提供商只检查配置，不主动调用外部模型，避免第三方短暂故障造成容器重启风暴。

数据库连接策略由统一存储组件管理，包括 WAL、外键、忙等待和同步级别；启动完成后会写入 schema 版本。可在停机前后或定时任务中执行完整性检查与 SQLite 在线备份：

```powershell
uv run enterprise-rag storage --database data/enterprise_rag.db verify
uv run enterprise-rag storage --database data/enterprise_rag.db backup `
  --output backups/enterprise-rag.db
```

备份命令先验证源库，再使用 SQLite 在线备份 API 生成一致快照，随后对快照执行 `quick_check`，并输出带 SHA-256、schema 版本和文件大小的 `.manifest.json`。它不会覆盖已有备份。生产模式还要求 `RAG_DATABASE_PATH` 使用绝对持久化路径。

## 生产安全和容器

`production` 环境要求至少 16 字符的 `RAG_API_KEY`、绝对数据库路径，并拒绝 `RAG_TRUSTED_HOSTS=*`；同时关闭 Swagger/ReDoc。基础限流由 `RAG_RATE_LIMIT_REQUESTS_PER_MINUTE` 控制，设置为 `0` 可关闭。

Docker Compose 使用非 root 用户、只读根文件系统、独立 SQLite 数据卷、capability drop 和 `no-new-privileges`：

```powershell
docker compose up --build -d
docker compose ps
```

完整部署、探针、故障定位、数据卷和生产边界参见 [运维手册](docs/OPERATIONS.md)。

## 最终端到端验收

服务启动后运行：

```powershell
uv run enterprise-rag accept `
  --base-url http://127.0.0.1:8000 `
  --output outputs/final-acceptance.json
```

验收器会幂等播种隔离的验收文档、FAQ 和 KG，然后验证安全拒绝、闲聊、任务动作、FAQ 精确命中、KG 回答、带引用 RAG、证据不足、违规答案转人工、审核后 SSE、答案评测、Prometheus 指标与 SLO。任一场景失败时命令返回非零退出码。

最终交付范围、扩展接口和上线前必做事项参见 [交付说明](docs/DELIVERY.md)。

## 安全与分层路由 API

```powershell
$body = @{
  query = "我的车撞了怎么办"
  actor_type = "consumer"
  context = @{}
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/routing/route `
  -ContentType application/json `
  -Body $body
```

目标模块包括 `reject`、`chitchat`、`task_flow`、`kbqa` 和 `rag`。响应同时返回安全命中、受众、领域、子意图、所需槽位、多轮继承标志和逐阶段决策轨迹。

路由词表、安全正则和任务/问答白名单位于 `config/routing.json`。系统先做关键词白名单判断，未直接命中时使用最近意图分类器兜底；`intent.source` 会标记为 `keyword`、`nearest_intent` 或 `context`。阈值通过 `RAG_ROUTING_MIN_INTENT_CONFIDENCE`、`RAG_ROUTING_MIN_DOMAIN_CONFIDENCE` 和 `RAG_ROUTING_FALLBACK_SIMILARITY` 调整。

## Task Flow 与统一问答入口

统一入口会自动完成安全检测、路由、任务状态恢复，并调用 Task Flow 或 KBQA：

```powershell
$body = @{
  query = "我要预约保养"
  conversation_id = "demo-conversation"
  provided_slots = @{}
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/assistant/respond `
  -ContentType application/json `
  -Body $body
```

继续使用相同的 `conversation_id` 提交 VIN、时间和服务中心。槽位齐全后会调用动作适配器；默认适配器只在本地生成模拟业务编号，不会对真实 CRM、理赔或预约系统产生外部副作用。可通过实现 `ActionAdapter` 并注册到 `ActionRegistry` 接入真实后端。

查询最近任务状态：`GET /api/v1/tasks/{conversation_id}`。

## KBQA 与知识图谱

FAQ 导入时只有显式设置 `approved: true` 的记录才能参与精确直返和 KBQA：

```json
{
  "items": [
    {
      "question": "保修期多久？",
      "answer": "请以随车保修手册为准。",
      "approved": true
    }
  ]
}
```

知识图谱三元组通过 `POST /api/v1/kbqa/kg/triples/import` 导入，直接测试 KBQA 使用 `POST /api/v1/kbqa/query`。FAQ 未精确命中时，FAQ 召回与 KG 查询并行执行；候选答案依次通过候选置信度、答案审核和审核后置信度门控。任一阶段低于配置阈值都会返回 `target: rag`。

## Docker

安装 Docker 后可执行：

```powershell
docker compose up --build
```

## 质量检查

```powershell
uv run ruff check .
uv run mypy
uv run pytest --cov=enterprise_rag --cov-report=term-missing
```

## 配置约定

所有环境变量使用 `RAG_` 前缀。`.env` 不提交到版本库；可提交的示例位于 `.env.example`。请求日志为 JSON 格式，每个请求都会返回 `X-Request-ID` 和 `X-Process-Time-Ms` 响应头。

