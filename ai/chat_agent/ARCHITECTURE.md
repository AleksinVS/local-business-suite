# Chat and Agent Block

This document defines the AI-facing block of `local-business-suite` as an architectural template.
It is intentionally implementation-agnostic at the service boundaries and assumes the existing Django app remains the system of record.

## Purpose

The chat and agent block provides a natural-language interface for internal users to:

- create and update business objects through controlled tools;
- query operational data with role-aware filters;
- receive summaries and structured responses inside chat;
- delegate multi-step work to an orchestrated agent.

The block is not a parallel business system. It is an interaction layer over the existing domain model, policies, and service layer.

## Recommended MVP Stack

- `LibreChat` as the multi-user chat UI.
- `LangGraph` as the agent orchestrator for multi-step flows and human-in-the-loop execution.
- `MCP` as the tool protocol between the chat/agent layer and the application-specific tools.
- A Python tool gateway that calls the existing domain services and policy checks.

Other chat frontends or orchestrators can be swapped later if they preserve the same tool contracts.

## Core Rules

- The chat layer must not bypass policy checks.
- Write actions must go through application services, not raw UI-driven SQL.
- Read actions may use read-only repository access or read-only SQL, but only through declared tools.
- Every tool invocation must be auditable.
- Tool behavior is declared in JSON contracts, not implied by prompts.
- The agent may ask clarifying questions before executing unsafe or incomplete requests.

## Runtime Boundaries

### Human Interface

The human interacts with the system through the chat UI. The UI is responsible for authentication, conversation history, and message presentation.

### Agent Orchestrator

The orchestrator manages:

- intent classification;
- slot filling;
- tool selection;
- confirmation before write actions;
- multi-step execution;
- structured responses back to the user.

### Tool Gateway

The tool gateway exposes a fixed set of read and write operations.
It converts agent requests into application-level operations and returns structured results.

### Domain Services

The domain services remain the single place where business rules are enforced.
Tools must call these services instead of duplicating workflow logic.

### Data Layer

Operational data stays in the primary application database.
The agent reads from the same domain data model through declared tools.
Direct writes are not allowed outside application services.

## Data Access Model

There are three access modes:

1. Read-only access for lookups, summaries, and list queries.
2. Service-mediated writes for creation, updates, and transitions.
3. Administrative actions for privileged operations such as assignments, catalog edits, or bulk changes.

The agent should be able to answer questions like:

- show new requests;
- create a request for a department;
- move a request to the next allowed status;
- add a comment;
- summarize workload by department.

## Tool Classes

### Read Tools

Read tools return filtered operational data.
They are safe by default, but still subject to role-based visibility.

### Write Tools

Write tools create or change data.
They require:

- authorization;
- policy validation;
- confirmation when the action is ambiguous or destructive;
- audit logging.

### Administrative Tools

Administrative tools handle assignments, dictionary maintenance, and bulk operations.
They are only available to elevated roles.

## Identity and Authorization

The user identity must be propagated from the chat UI to the tool gateway.
The tool gateway must treat the caller as an application user, not as a generic agent session.

Minimum identity context:

- application user id;
- role list;
- organization or department scope when applicable;
- session or conversation id;
- request correlation id.

Authorization decisions must be consistent with the application policy model.

## Interaction Pattern

1. The user sends a natural-language request.
2. The agent classifies the intent.
3. The agent resolves missing slots if needed.
4. The agent selects a tool from the registry.
5. The tool gateway validates the request against policy.
6. The domain service executes the change or read.
7. The agent formats the result for the chat UI.

## Minimum MVP Scope

The first delivery should support:

- listing requests by status and scope;
- creating a request with a department and optional device;
- reading request details;
- transitioning a request to an allowed status;
- adding a comment;
- listing departments and devices for selection.

## Future Expansion

The same block can later support:

- legacy system bridges;
- analytics questions;
- attachment handling;
- bulk requests;
- guided workflows with approval steps.

