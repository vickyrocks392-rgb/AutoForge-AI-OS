# Memory Engine

> **⚠️ LEGACY / SUPERSEDED-IN-PART (2026-08-26):** This short-form document predates the frozen **Memory Platform Specification v1.0** (`docs/subsystems/MEMORY_PLATFORM_SPECIFICATION.md`), which is authoritative for Memory. The Memory ≠ Learning boundary is fixed in **`docs/adr/ADR-005`**. Where this document disagrees, the frozen specification and the ADR win.

> **Note:** This document is consistent with Architecture v1.0 (`architecture/ARCHITECTURE.md`). The Memory Engine is a Shared Platform Service that provides contextual storage capturing the state and history of specific executions and sessions. It manages working memory, project memory, long-term memory, reflection memory, and semantic memory.

## Purpose

This document describes the Memory Engine — the Shared Platform Service responsible for managing contextual storage, execution history, and knowledge persistence across the AutoForge AI platform. It provides the data infrastructure that enables workflows to be recoverable, workers to have context, and decisions to be auditable.

## Scope

This document covers the conceptual architecture of the Memory Engine, its memory types, data models, and relationship to other platform components. Implementation details are deferred to the `packages/memory` package. The canonical specification for the Memory Engine is in `architecture/ARCHITECTURE.md` Section 14.

---

## Overview

The Memory Engine is the persistence backbone of AutoForge AI. It manages three tiers of memory — short-term, long-term, and vector — each serving a distinct purpose in the platform's operation. It ensures that no state is lost, no context is forgotten, and every decision can be traced.

## Memory Tiers

### Short-Term Memory
- **Purpose** — Active workflow state, in-progress task contexts, current agent sessions.
- **Characteristics** — Fast, ephemeral, bounded size.
- **Backend** — In-memory cache (Redis).
- **Lifetime** — Duration of a workflow or session.

### Long-Term Memory
- **Purpose** — Completed workflow records, task results, generated artifacts, audit logs.
- **Characteristics** — Durable, queryable, append-only.
- **Backend** — Relational database (PostgreSQL).
- **Lifetime** — Indefinite.

### Vector Memory
- **Purpose** — Semantic search over past decisions, code patterns, architectural choices, and agent interactions.
- **Characteristics** — Embedding-based, similarity search, high-dimensional.
- **Backend** — Vector database (pgvector, Pinecone, or similar).
- **Lifetime** — Indefinite.

## Key Responsibilities

- **State Persistence** — Save and restore workflow and task state for recovery and audit.
- **Context Management** — Provide relevant context to agents based on current task and historical data.
- **Artifact Storage** — Store and retrieve generated artifacts (code, documentation, diagrams).
- **Semantic Retrieval** — Enable agents to search past decisions and patterns using vector similarity.
- **Audit Trail** — Maintain an immutable log of all state changes and decisions.

## Data Model

- **WorkflowRecord** — Persisted state of a workflow execution.
- **TaskRecord** — Persisted state of a task execution within a workflow.
- **ArtifactRecord** — Metadata and reference to a generated artifact.
- **ContextSnapshot** — A point-in-time capture of execution context for recovery.
- **DecisionLog** — An immutable entry recording a decision made during execution.
- **EmbeddingRecord** — A vector embedding with associated metadata for semantic search.

## Future Topics

- Memory pruning and garbage collection strategies
- Context window optimization for LLM token limits
- Cross-project memory and knowledge transfer
- Memory compression and summarization
- Caching strategies for frequently accessed context
- Data retention policies and compliance
- Memory encryption and access control