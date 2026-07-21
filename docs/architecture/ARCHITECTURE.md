# Architecture Guide

Welcome to the `local-business-suite` architecture documentation. This project is built as a **local-first Django monorepo** designed for internal business systems with integrated AI capabilities.

## High-Level Overview

The system is organized into several layers:
1.  **Core Platform:** Django-based monorepo providing authentication, roles, shared dictionaries, and the primary web interface.
2.  **AI Block:** An autonomous agent runtime based on LangGraph and MCP that interacts with the platform via a secure tool gateway.
3.  **Memory Layer:** Django-owned AI memory moving toward file-backed accepted knowledge, separate source data, separate indexes, graph facts, document ingestion, moderated graph schema bootstrapping, chat-derived personal/organization memory, secret handles and planned external information system connectors.
4.  **Analytics Layer:** A knowledge-driven business analytics path that combines memory deltas, email contents, documents, optional DMS/API enrichment, Parquet/DuckDB storage, metric monitors and AI diagnostic workflows.

## Key Documentation

For a deep dive into specific areas, please refer to the following documents:

- **[Blueprint](blueprint.md)**: The foundational document describing the architectural vision, principles (Local-first, Server-driven UI, Policy-first), and the overall tech stack.
- **[Domain Model](DOMAIN_MODEL.md)**: High-level overview of the main business entities and modules.
- **[Policy Model](POLICY_MODEL.md)**: Detailed description of the role-based access control and declarative policy system.
- **[AI UI Protocol Foundation](AI_UI_PROTOCOL_FOUNDATION_PLAN.md)** & **[Native AG-UI Chat Development](NATIVE_AG_UI_CHAT_DEVELOPMENT_PLAN.md)**: Technical design of the AI chat surface, UI protocol/driver matrix, tool gateway and confirmation flows.
- **[Integrations](INTEGRATIONS.md)**: Strategy for connecting with legacy enterprise systems (Bridges).
- **[Analytics Model](ANALYTICS_MODEL.md)**: Design of the analytical layer (Parquet + DuckDB + Evidence).
- **[Observability Baseline](OBSERVABILITY_BASELINE.md)**: Minimal p50/p95 metrics and local latency event reporting before performance or stack decisions.
- **[Service Extraction Guide](SERVICE_EXTRACTION_GUIDE.md)**: Rules for safely extracting technical workers/services while keeping Django as the business source of truth.
- **[Design Patterns Review](DESIGN_PATTERNS_REVIEW_2026-06-01.md)**: Recommended design patterns for the current Django monorepo, AI gateway, contracts, memory, analytics and future workers.
- **[PostgreSQL Primary Store Plan](POSTGRESQL_PRIMARY_STORE_PLAN.md)**: Target migration from SQLite-separated runtime files to one PostgreSQL primary store, with SQLite moved to a separate fork.
- **[PWA and Tauri Notifications Plan](PWA_AND_TAURI_NOTIFICATIONS_PLAN.md)**: PWA-first user notifications without third-party Web Push and optional Tauri tray client.
- **[Knowledge-driven Analytics Plan](KNOWLEDGE_DRIVEN_ANALYTICS_PLAN.md)**: Continuous business analytics from memory, email contents, documents, optional DMS and AI diagnostics.
- **[Memory Service Plan](MEMORY_SERVICE_IMPLEMENTATION_PLAN.md)**: Implementation plan for the AI memory service.
- **[Memory Ingestion and Bootstrapping Plan](MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md)**: Final plan for corporate document ingestion and graph schema bootstrapping.
- **[Memory Completion Gap Analysis](MEMORY_COMPLETION_GAP_ANALYSIS.md)**: Current gaps between implemented MVP and target memory system.
- **[Chat Memory and Secret Handles Plan](MEMORY_CHAT_REFLECTION_AND_SECRET_HANDLES_PLAN.md)**: Plan for `memory.remember`, sleep-time reflection, organization candidates and secret handles.
- **[External Systems Connector Plan](MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_PLAN.md)**: Plan for collecting knowledge from external information systems through queued connectors and normalized landing zone.
- **[File-backed Knowledge Plan](MEMORY_FILE_BACKED_KNOWLEDGE_PLAN.md)**: Target memory architecture with accepted knowledge in Git-versioned files, separate databases, temporary source processing and unified search over knowledge and source data.

## Core Principles

- **Local-first**: Designed to run on-premise without cloud dependencies.
- **Server-driven UI**: Uses Django Templates and HTMX for a responsive yet simple frontend.
- **Policy-first**: Business logic and authorization are centralized on the server.
- **Config-driven**: Roles and Workflows are defined in versioned JSON contracts.

## Architecture Decision Records (ADR)

Significant design choices are documented in the [ADR directory](../adr/):
- [ADR-0001: Local-first monorepo architecture](../adr/ADR-0001-local-first-monorepo.md)
- [ADR-0002: Config-driven policy and workflow](../adr/ADR-0002-config-driven-policy-and-workflow.md)
- [ADR-0003: AI memory service architecture](../adr/ADR-0003-ai-memory-service.md)
- [ADR-0004: Memory ingestion connector and graph schema bootstrapping](../adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md)
- [ADR-0005: Chat-derived memory, reflection jobs and secret handles](../adr/ADR-0005-chat-derived-memory-and-secret-handles.md)
- [ADR-0006: External system knowledge connectors](../adr/ADR-0006-external-system-knowledge-connectors.md)
- [ADR-0008: Knowledge-driven business analytics](../adr/ADR-0008-knowledge-driven-business-analytics.md)
- [ADR-0011: File-backed knowledge and unified search](../adr/ADR-0011-file-backed-knowledge-and-unified-search.md)
- [ADR-0024: Service extraction readiness](../adr/ADR-0024-service-extraction-readiness.md)
- [ADR-0026: PWA-first notifications and optional Tauri client](../adr/ADR-0026-pwa-first-and-optional-tauri-notifications.md)
- [ADR-0029: PostgreSQL primary store and SQLite fork](../adr/ADR-0029-postgresql-primary-store-and-sqlite-fork.md)
- [ADR-0030: Memory alignment to hybrid-knowledge v0.5](../adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md)
- [ADR-0031: Runtime contract store and delivery](../adr/ADR-0031-runtime-contract-store-and-delivery.md)
- [ADR-0032: Retire legacy AI UI driver](../adr/ADR-0032-retire-legacy-ai-ui-driver.md)
- [ADR-0033: Native AI UI asset versions and staticfiles sync](../adr/ADR-0033-native-ai-ui-asset-versions-and-staticfiles-sync.md)
