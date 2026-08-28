# Packages

## Purpose

This directory contains shared libraries and modules that provide foundational infrastructure for the AutoForge AI platform. Packages are consumed by apps and services to ensure consistency and reduce duplication.

## Responsibility

- Provide reusable types, utilities, and constants
- Implement core infrastructure (workflows, prompts, models, memory, tools)
- Enforce consistent interfaces and contracts across the platform
- Abstract external dependencies and integrations

## Future Contents

- `shared/` — Common types, interfaces, constants, and utilities
- `prompts/` — Prompt templates, management, and versioning
- `workflows/` — Workflow engine for service orchestration
- `models/` — Data models, schemas, and validation
- `memory/` — State management, persistence, and context storage
- `tools/` — Shared tool definitions and external integrations
- `security/` — Deterministic Security & Governance Platform (Phase 15, ADR-016)