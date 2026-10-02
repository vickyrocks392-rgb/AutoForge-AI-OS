# AutoForge Learning (Phase 19)

Phase 19B-1 foundation: immutable learning domain models, authoritative
evidence representation, real evidence collection, and the `ProposalGateway`
security boundary.

## What this package is

* **Immutable models only.** `ExperienceRecord`, `EvidenceRef`,
  `LearningSignal`, `LearningCandidate`, `ProposalDecision`, `ValidationSummary`.
* **Evidence collection** from existing authoritative systems
  (durable artifact catalog, completion/validation results, runtime state).
* **`ProposalGateway`** — the *only* sanctioned entry point for a learning
  candidate, which routes every proposal through the certified
  `AIGuardrailsEngine.evaluate_learning_proposal()` boundary.

## What this package is NOT

* It does **not** promote candidates.
* It does **not** activate anything.
* It does **not** modify source code.
* It does **not** grant authority. Level 5 is unreachable by construction.

`ProposalGateway` returning `PERMITTED` means only *"this proposal may proceed
to the next controlled learning stage."* It does **not** mean approved,
promoted, or activated.

## Architecture basis

All decisions derive from the Gate 19A documents in `phase19/`. This package
implements M-01, M-02 (models only), M-03, and — critically — **M-04**, the
non-negotiable production call site into `evaluate_learning_proposal()`.