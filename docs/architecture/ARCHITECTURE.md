# Architecture Guide

Welcome to the `local-business-suite` architecture documentation. This project is built as a **local-first Django monorepo** designed for internal business systems with integrated AI capabilities.

## High-Level Overview

The system is organized into several layers:
1.  **Core Platform:** Django-based monorepo providing authentication, roles, shared dictionaries, and the primary web interface.
2.  **AI Block:** An autonomous agent runtime based on LangGraph and MCP that interacts with the platform via a secure tool gateway.
3.  **Analytics Layer:** A separate analytical path that uses Parquet exports and DuckDB for efficient querying without stressing the OLTP database.

## Key Documentation

For a deep dive into specific areas, please refer to the following documents:

- **[Blueprint](blueprint.md)**: The foundational document describing the architectural vision, principles (Local-first, Server-driven UI, Policy-first), and the overall tech stack.
- **[Domain Model](DOMAIN_MODEL.md)**: High-level overview of the main business entities and modules.
- **[Policy Model](POLICY_MODEL.md)**: Detailed description of the role-based access control and declarative policy system.
- **[AI Architecture](../../ai/chat_agent/ARCHITECTURE.md)**: Technical details of the AI agent, tool gateway, and confirmation flows.
- **[Integrations](INTEGRATIONS.md)**: Strategy for connecting with legacy enterprise systems (Bridges).
- **[Analytics Model](ANALYTICS_MODEL.md)**: Design of the analytical layer (Parquet + DuckDB + Evidence).

## Core Principles

- **Local-first**: Designed to run on-premise without cloud dependencies.
- **Server-driven UI**: Uses Django Templates and HTMX for a responsive yet simple frontend.
- **Policy-first**: Business logic and authorization are centralized on the server.
- **Config-driven**: Roles and Workflows are defined in versioned JSON contracts.

## Architecture Decision Records (ADR)

Significant design choices are documented in the [ADR directory](../adr/):
- [ADR-0001: Local-first monorepo architecture](../adr/ADR-0001-local-first-monorepo.md)
- [ADR-0002: Config-driven policy and workflow](../adr/ADR-0002-config-driven-policy-and-workflow.md)
