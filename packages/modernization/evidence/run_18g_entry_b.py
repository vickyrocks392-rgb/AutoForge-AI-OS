"""18-G Run 7 entry B: AI tasks + strip + one full AutoForge run."""
import time
import uuid
from pathlib import Path

from run_18g_pipe_d1 import pipe_closure, pipe_discover
from run_18g_pipe_d2 import (
    pipe_build,
    pipe_generate,
    pipe_inference,
    pipe_plan,
    pipe_semantics,
)
from run_18g_pipe_e import pipe_runtime
from run_18g_pipe_f import pipe_repair
from run_18g_pipe_g import pipe_package, pipe_provenance, pipe_purge

from run_18g_entry_a import (
    CODING,
    COMMIT,
    HP_CODING,
    HP_URL,
    M1_URL,
    REASON,
    REPO_ROOT,
    _java_bin,
    _rag,
    async_call_ollama,
    http_get,
    sha256_of,
)

from autoforge_kernel.project_lifecycle import (
    ProjectLifecycleManager,
    ProjectPersistencePolicy,
    ProjectState,
)
from autoforge_modernization.composition.app_runner import SpringBootApplicationRunner
from autoforge_modernization.composition.generator import (
    GeneratedArtifact,
    GenericTargetArtifactGenerator,
)
from autoforge_modernization.composition.planner import GenericTransformationPlanner
from autoforge_modernization.composition.repair import AutonomousTargetRepairCycle
from autoforge_modernization.composition.verifier import TargetToolchainVerifier
from autoforge_modernization.composition.workload_selector import (
    TransformationWorkloadSelector,
)
from autoforge_modernization.discovery.engine import ProjectTechnologyDiscoveryEngine
from autoforge_modernization.provenance import (
    ModernizationProvenanceChain,
    ProvenanceLink,
    ProvenanceStage,
)
from autoforge_modernization.target.specification import TargetSpecification
from autoforge_kernel.project_lifecycle import (
    ProjectPurgeVerifier,
    ProjectResourceRegistry,
)
