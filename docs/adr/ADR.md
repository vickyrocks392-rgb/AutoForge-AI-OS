# Architecture Decision Records

## Purpose

Architecture Decision Records (ADRs) document significant architectural decisions made during the development of AutoForge AI. Each ADR captures the context, decision, consequences, and alternatives considered, providing a historical record of why the system is designed the way it is.

---

## ADR Template

Use the following template when recording a new architecture decision.

---

### ADR-{NNN}: {Title}

**Date:** {YYYY-MM-DD}

**Status:** {Proposed | Accepted | Deprecated | Superseded}

---

#### Context

{Describe the problem, background, and forces that led to this decision. Include relevant constraints, requirements, and trade-offs.}

---

#### Decision

{Describe the decision that was made. Be specific about what was chosen and why.}

---

#### Consequences

{Describe the positive and negative consequences of this decision. What trade-offs were made? What becomes easier or harder?}

---

#### Alternatives Considered

| Alternative | Reason for Rejection |
|---|---|
| {Alternative 1} | {Why it was not chosen} |
| {Alternative 2} | {Why it was not chosen} |
| {Alternative 3} | {Why it was not chosen} |

---

### ADR Index

| ADR | Title | Status | Date |
|---|---|---|---|
| ADR-001 | Canonical Event Vocabulary and Event Platform Boundary | Accepted | 2026-08-26 |
| ADR-002 | Composition Root and Kernel-Runtime Boundary | Accepted | 2026-08-26 |
| ADR-003 | Context Engineering Contract (Architecture Only) | Accepted | 2026-08-26 |
| ADR-004 | Engineering Experience Contract (Read Model) | Accepted | 2026-08-26 |
| ADR-005 | Memory ≠ Learning Boundary (Specification Amendment) | Accepted | 2026-08-26 |