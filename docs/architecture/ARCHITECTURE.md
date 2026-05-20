# Architecture Guide

Welcome to the `local-business-suite` architecture documentation. This project is built as a **local-first Django monorepo** designed for internal business systems with integrated AI capabilities.

## High-Level Overview

The system is organized into several layers:
1.  **Core Platform:** Django-based monorepo providing authentication, roles, shared dictionaries, and the primary web interface.
2.  **AI Block:** An autonomous agent runtime based on LangGraph and MCP that interacts with the platform via a secure tool gateway.
3.  **Memory Layer:** Django-owned AI memory with safe corpus, retrieval tools, graph facts, document ingestion, moderated graph schema bootstrapping, chat-derived personal/organization memory, secret handles and planned external information system connectors.
4.  **Analytics Layer:** A separate analytical path that uses Parquet exports and DuckDB for efficient querying without stressing the OLTP database.

## Key Documentation

For a deep dive into specific areas, please refer to the following documents:

- **[Blueprint](blueprint.md)**: The foundational document describing the architectural vision, principles (Local-first, Server-driven UI, Policy-first), and the overall tech stack.
- **[Domain Model](DOMAIN_MODEL.md)**: High-level overview of the main business entities and modules.
- **[Policy Model](POLICY_MODEL.md)**: Detailed description of the role-based access control and declarative policy system.
- **[AI Architecture](../../ai/chat_agent/ARCHITECTURE.md)**: Technical details of the AI agent, tool gateway, and confirmation flows.
- **[Integrations](INTEGRATIONS.md)**: Strategy for connecting with legacy enterprise systems (Bridges).
- **[Analytics Model](ANALYTICS_MODEL.md)**: Design of the analytical layer (Parquet + DuckDB + Evidence).
- **[Memory Service Plan](MEMORY_SERVICE_IMPLEMENTATION_PLAN.md)**: Implementation plan for the AI memory service.
- **[Memory Ingestion and Bootstrapping Plan](MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md)**: Final plan for corporate document ingestion and graph schema bootstrapping.
- **[Memory Completion Gap Analysis](MEMORY_COMPLETION_GAP_ANALYSIS.md)**: Current gaps between implemented MVP and target memory system.
- **[Chat Memory and Secret Handles Plan](MEMORY_CHAT_REFLECTION_AND_SECRET_HANDLES_PLAN.md)**: Plan for `memory.remember`, sleep-time reflection, organization candidates and secret handles.
- **[External Systems Connector Plan](MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_PLAN.md)**: Plan for collecting knowledge from external information systems through queued connectors and normalized landing zone.

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
