# AutoForge Power Engines

Canonical implementation of commercial Power Engines for AutoForge AI OS (Phase 18-COMMERCIAL).

## Implemented Power Engines:
- **18-COMMERCIAL-A**: RAG Knowledge Power Engine (`autoforge_power_engines.rag.engine.RAGKnowledgePowerEngine`)

## Architectural Contract:
1. **Autonomy by Default, Human Intervention by Exception**: Executes all 11 stages autonomously unless an explicit risk condition requires human approval.
2. **Canonical 11-Stage Lifecycle**:
   `INTAKE → UNDERSTAND/ANALYZE → PLAN → EXECUTE → OBSERVE → VERIFY → DIAGNOSE → REPAIR → RE-VERIFY → PACKAGE → DELIVER`
3. **Strict Proprietary Boundary**: Customer deliverables NEVER contain AutoForge internal source code or runtime imports of AutoForge.
4. **Isolated Workspaces**: Customer deliveries are written to `AUTOFORGE_OUTPUT_ROOT/<project-name>/<delivery-id>/`.
