# Roadmap

**Goal:** if a client says "I want this AI app for N users", be able to design and build it end to end: backend, AI, scalability, cloud and industry-standard practices.

## P1 — ComplianceIQ (BFSI, advanced RAG)
A compliance copilot for banks and NBFCs that answers questions about RBI/SEBI circulars with circular- and section-level citations.
- **Ingestion:** layout-aware PDF and table parsing, metadata extraction (circular no., date, supersedes), parent-child chunking, contextual chunk headers, dedupe, version graph.
- **Retrieval:** hybrid search (Postgres full-text + pgvector HNSW), RRF fusion, metadata/ACL filters, cross-encoder reranking, query rewriting, multi-query, HyDE, query router, parent-document retrieval.
- **Generation:** grounded answers with citations, "not found" refusal, citation self-check, SSE streaming, follow-up condensing, version-aware notes.
- **Platform:** JWT auth, document ACL, Redis semantic cache, rate limiting, LLM provider abstraction (Bedrock + direct API with fallback), cost per query.
- **Evals:** 150+ golden questions; Recall@k, MRR, nDCG; ablation table; faithfulness/relevance/citation accuracy via a calibrated LLM judge; CI gate.
- **Ops:** Docker Compose → EC2 + Nginx + HTTPS, GitHub Actions, Langfuse, Locust load test, capacity plan.
- No LangChain/LlamaIndex: the pipeline is built by hand.

Milestones: [project-1-complianceiq/docs/MILESTONES.md](project-1-complianceiq/docs/MILESTONES.md)

## P2 — IncidentPilot (IT Ops / AIOps agent)
Demo microservices + Prometheus/Loki/Grafana + chaos injector; MCP servers (metrics, logs, GitHub, containers, runbooks via P1's RAG, Slack, Jira); LangGraph flow triage → parallel investigators → root cause → plan → **human approval** → execute → verify; guardrails; 30+ scenario eval library with trajectory and safety evals. Infra: ECS Fargate, Terraform.

## P3 — VoiceDesk (master project)
Multi-tenant voice agents: streaming STT → LLM → TTS under ~800 ms, turn detection, barge-in; LiveKit/Pipecat + Twilio SIP; per-tenant knowledge base (P1) and tools (P2); LLM gateway with fallbacks and per-tenant billing; human handoff; call analytics. Infra: EKS autoscaling on concurrent calls, Terraform, cost per 1,000 minutes.

## Cloud strategy
Deep on AWS (EC2, S3, RDS, ElastiCache, ECS, EKS, Bedrock). Vertex AI and Azure OpenAI as extra gateway providers. Snowflake/Databricks: conceptual only.
