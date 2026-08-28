# AutoForge AI

**Production-Grade Autonomous Software Engineering Platform**

AutoForge AI is not another coding assistant. It is an autonomous platform engineered to execute the entire Software Development Life Cycle (SDLC) through specialized AI agents — with full transparency, modularity, recoverability, and production readiness at its core.

---

## Project Vision

To redefine how software is built by creating an autonomous engineering system that plans, researches, architects, implements, tests, deploys, and documents software — operating with the rigor and discipline of a senior engineering team, but at machine speed and scale.

AutoForge AI aims to be the operating system for AI-driven software development.

See the full [Vision Document](architecture/VISION.md) for a deeper articulation of the long-term vision.

---

## Project Philosophy

AutoForge AI is built on the belief that software engineering can and should be automated — not by replacing human creativity with a single monolithic AI, but by orchestrating a team of specialized AI agents that each excel at a specific phase of the SDLC.

We treat AI agents as **AI employees** — each with a defined role, clear responsibilities, and measurable outputs. The platform is their employer, manager, and infrastructure rolled into one.

This is not assisted coding. This is autonomous engineering.

---

## Engineering Principles

The following principles guide every architectural decision in this project. See [Principles](architecture/PRINCIPLES.md) for the full document.

1. **Separation of Concerns** — Each service owns one domain. No overlap. No ambiguity.
2. **Contract-First Design** — Services communicate through strict, versioned interfaces.
3. **Determinism Where Possible** — Given the same inputs and context, outputs should be reproducible.
4. **Fail Gracefully** — Every component handles errors, logs context, and degrades safely.
5. **Humans in the Loop** — AI drives execution; humans review, approve, and steer.
6. **Transparency by Default** — Every decision, artifact, and action is logged, versioned, and inspectable.
7. **Incremental Value** — Each iteration produces a working, verifiable artifact.
8. **Composition Over Inheritance** — Capabilities are composed from small, focused units.
9. **Convention Over Configuration** — Sensible defaults exist for everything.
10. **Observable by Design** — Every component emits structured logs, metrics, and traces.

---

## The Execution Engine

The **Execution Engine** (`packages/execution`) is the operational heart of AutoForge AI. It is the runtime that receives plans from the workflow engine, dispatches work to AI agent services, monitors execution, manages state, and ensures completion.

While the workflow engine defines *what* to do and *when*, the Execution Engine determines *how* it actually happens — managing resources, retries, timeouts, and the physical act of running agent tasks.

See [Execution Engine](docs/subsystems/EXECUTION_ENGINE.md) for the full architecture document.

---

## Planned Technology Stack

| Layer | Technology |
|---|---|
| **Runtime** | Node.js / TypeScript |
| **API Layer** | REST / GraphQL |
| **Service Orchestration** | Custom workflow engine (`packages/workflows`) |
| **Execution Runtime** | Custom execution engine (`packages/execution`) |
| **Agent Framework** | LangChain / Custom |
| **State & Memory** | PostgreSQL / Redis / Vector Store |
| **Message Queue** | RabbitMQ / NATS |
| **Containerization** | Docker |
| **Orchestration** | Kubernetes (for production deployments) |
| **CI/CD** | GitHub Actions |
| **Monitoring** | OpenTelemetry / Prometheus / Grafana |
| **Documentation** | Markdown / Mermaid / OpenAPI |

*Note: Specific versions and exact tooling will be finalized during implementation phases.*

---

## Repository Layout

```
AutoForge-AI/
├── apps/                    # Runnable applications
│   ├── api/                 # Public API gateway
│   └── web/                 # Web interface
├── services/                # AI agent services (SDLC phases)
│   ├── planner/             # Task decomposition & planning
│   ├── research/            # Context gathering & research
│   ├── requirements/        # Requirements analysis & specification
│   ├── architecture/        # System design & architecture
│   ├── ui/                  # UI/UX generation
│   ├── backend/             # Backend code generation
│   ├── frontend/            # Frontend code generation
│   ├── testing/             # Test generation & execution
│   ├── deployment/          # Deployment & infrastructure
│   └── documentation/       # Documentation generation
├── packages/                # Shared libraries & modules
│   ├── shared/              # Common types, utilities, constants
│   ├── prompts/             # Prompt templates & management
│   ├── workflows/           # Workflow engine & orchestration
│   ├── execution/           # Execution runtime & task dispatch
│   ├── models/              # Data models & schemas
│   ├── memory/              # State management & persistence
│   └── tools/               # Shared tool definitions & integrations
├── docs/                    # Documentation
├── docker/                  # Docker configurations
├── scripts/                 # Build & utility scripts
├── tests/                   # Integration & E2E tests
├── examples/                # Usage examples & demos
└── .github/                 # GitHub configuration
    ├── ISSUE_TEMPLATE/      # Issue templates
    ├── PULL_REQUEST_TEMPLATE.md
    └── workflows/           # CI/CD workflow definitions
```

---

## Documentation Index

| Document | Description |
|---|---|
| [Vision](architecture/VISION.md) | Long-term vision and aspirational direction |
| [Principles](architecture/PRINCIPLES.md) | Core engineering and design principles |
| [Architecture](architecture/ARCHITECTURE.md) | Canonical architecture specification (v1.0) |
| [Execution Engine](docs/subsystems/EXECUTION_ENGINE.md) | The operational runtime for AI agent tasks |
| [AI Organization](docs/subsystems/AI_ORGANIZATION.md) | How AI agents are structured and collaborate |
| [Agent Protocol](docs/subsystems/AGENT_PROTOCOL.md) | Communication protocol between engine and agents |
| [Task Engine](docs/subsystems/TASK_ENGINE.md) | Task definition, lifecycle, and management |
| [Memory Engine](docs/subsystems/MEMORY_ENGINE.md) | State persistence, context, and knowledge management |
| [Repository Structure](architecture/REPOSITORY_STRUCTURE.md) | Canonical repository governance and organization |
| [Coding Standards](docs/standards/CODING_STANDARDS.md) | Code conventions, testing, and quality standards |
| [ADR](docs/adr/ADR.md) | Architecture Decision Records template and index |

---

## Future Architecture

The platform is designed around four core engines that work together to enable autonomous software engineering:

1. **Workflow Engine** (`packages/workflows`) — Defines the DAG of work items and their dependencies.
2. **Execution Engine** (`packages/execution`) — Dispatches work to AI agents, manages resources, and handles recovery.
3. **Task Engine** (conceptual, spans `packages/workflows` and `packages/execution`) — Manages task lifecycle from definition through completion.
4. **Memory Engine** (`packages/memory`) — Persists state, context, and knowledge across workflows.

These engines are supported by a suite of **AI agent services** (`services/`) that each own a phase of the SDLC, and a set of **shared packages** (`packages/`) that provide common infrastructure.

---

## Canonical Roadmap

The authoritative implementation roadmap is documented in [`architecture/ROADMAP.md`](architecture/ROADMAP.md) and governed by [`architecture/ARCHITECTURE.md`](architecture/ARCHITECTURE.md).

| Phase | Subsystem / Layer | Status |
|---|---|---|
| **Phase 1** | Architecture Foundation | ✅ Frozen |
| **Phase 2** | Kernel | ✅ Frozen |
| **Phase 3** | Runtime State Manager | ✅ Frozen |
| **Phase 4** | Event Platform | ✅ Frozen |
| **Phase 5** | Knowledge Platform | ✅ Frozen |
| **Phase 6** | Memory Platform | ✅ Frozen |
| **Phase 7** | AI Infrastructure Platform | ✅ Frozen |
| **Phase 8** | Connector Platform | ✅ Frozen |
| **Phase 9** | Workflow Platform | ✅ Frozen |
| **Phase 10** | Execution Platform | ✅ Frozen |
| **Phase 11** | Review Platform | ✅ Frozen |
| **Phase 12** | Artifact Platform | ✅ Frozen |
| **Phase 13** | AI Workforce (23 Specialized Workers) | ✅ Frozen |
| **Phase 14** | Observability Platform & Dashboards | ✅ Frozen |
| **Phase 15** | Security & Governance Platform | ⏳ Planned |
| **Phase 16** | AutoForge Product Experience | ⏳ Planned |
| **Phase 17** | AI Runtime & Real Model Integration | ⏳ Planned |
| **Phase 18** | Autonomous Engineering & Modernization | ⏳ Planned |
| **Phase 19** | Continuous Learning & Self-Improvement | ⏳ Planned |
| **Phase 20** | Modernization Service MVP | ⏳ Planned |
| **Phase 21** | Desktop Application & Distribution | ⏳ Planned |
| **Phase 22** | Developer / Extension Platform | ⏳ Planned |
| **Phase 23** | Enterprise Platform | ⏳ Planned |
| **Phase 24** | Distributed AI Operating System | ⏳ Planned |
| **Phase 25** | Production Release (v1.0) | ⏳ Planned |

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

*AutoForge AI — Engineering the future of software engineering.*