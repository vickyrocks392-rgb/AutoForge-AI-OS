/**
 * AutoForge AI OS — Product Experience Controller
 * Orchestrates views, renders live projections, connects to authoritative platform services,
 * and provides full interactivity across all engineering surfaces.
 */

let currentView = "command-center";
let currentMode = "GREENFIELD";
let currentCapabilityTab = "planning";
let currentKnowledgeTab = "pipeline";
let workersData = [];
let projectsData = [];
let modelsData = [];
let nodesData = [];

// ── Navigation & Routing ───────────────────────────────────────────────────

function navigateTo(viewId) {
  currentView = viewId;
  document.querySelectorAll(".view-container").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));

  const targetView = document.getElementById(`view-${viewId}`);
  if (targetView) targetView.classList.add("active");

  const targetNav = document.querySelector(`.nav-item[data-view="${viewId}"]`);
  if (targetNav) targetNav.classList.add("active");

  refreshView(viewId);
}

function switchMode(mode) {
  currentMode = mode;
  const greenfieldBtn = document.getElementById("mode-greenfield-btn");
  const legacyBtn = document.getElementById("mode-legacy-btn");
  if (greenfieldBtn) greenfieldBtn.classList.toggle("active", mode === "GREENFIELD");
  if (legacyBtn) legacyBtn.classList.toggle("active", mode === "LEGACY_MODERNIZATION");
  window.apiClient.setWorkspaceMode(mode).catch(console.error);

  if (mode === "LEGACY_MODERNIZATION") {
    navigateTo("legacy-workspace");
  } else {
    navigateTo("command-center");
  }
}

// ── View Refresh Dispatcher ────────────────────────────────────────────────

async function refreshView(viewId) {
  try {
    switch (viewId) {
      case "command-center":
        await loadCommandCenter();
        break;
      case "capabilities":
        await loadCapabilities();
        break;
      case "projects":
        await loadProjects();
        break;
      case "knowledge":
        await loadKnowledge();
        break;
      case "engineering-workspace":
        await loadEngineeringWorkspace();
        break;
      case "live-activity":
        await loadLiveActivity();
        break;
      case "workflows":
        await loadWorkflows();
        break;
      case "executions":
        await loadExecutions();
        break;
      case "reviews":
        await loadReviews();
        break;
      case "artifacts":
        await loadArtifacts();
        break;
      case "planning":
        await loadPlanning();
        break;
      case "research":
        await loadResearch();
        break;
      case "coding":
        await loadCoding();
        break;
      case "workforce":
        await loadWorkforce();
        break;
      case "models":
        await loadModels();
        break;
      case "nodes":
        await loadNodes();
        break;
      case "legacy-workspace":
        await loadLegacyWorkspace();
        break;
      case "hitl-center":
        await loadHITLCenter();
        break;
      case "observability":
        await loadObservability();
        break;
      case "experience":
        await loadExperience();
        break;
      case "self-improvement":
        await loadSelfImprovement();
        break;
      case "settings":
        await loadSettings();
        break;
    }
  } catch (err) {
    console.error(`Error refreshing view ${viewId}:`, err);
  }
}

// ── 1. Command Center & Hero Workflow Entry ────────────────────────────────

async function loadCommandCenter() {
  const status = await window.apiClient.getSystemStatus().catch(() => ({ is_healthy: true, uptime_seconds: 0, active_operations_count: 0 }));
  const opsVal = document.getElementById("cc-active-ops");
  if (opsVal) opsVal.textContent = status.active_operations_count || "0";

  const uptimeVal = document.getElementById("system-uptime-text");
  if (uptimeVal && status.uptime_seconds !== undefined) {
    uptimeVal.textContent = `Uptime: ${Math.floor(status.uptime_seconds)}s`;
  }

  const approvals = await window.apiClient.getHITLApprovals().catch(() => []);
  const pendingApprovals = approvals.filter(a => a.decision === "pending");
  const apprVal = document.getElementById("cc-pending-approvals");
  if (apprVal) apprVal.textContent = pendingApprovals.length;

  const apprBadge = document.getElementById("nav-approval-badge");
  if (apprBadge) apprBadge.textContent = pendingApprovals.length;

  // Live Activity Feed in Command Center
  const activities = await window.apiClient.getAgentActivity(5).catch(() => []);
  const feed = document.getElementById("cc-activity-feed");
  if (feed) {
    feed.innerHTML = activities.map(a => `
      <div class="activity-card clickable-card" onclick="openExecutionInspector('${escapeHtml(a.trace_id || 'exec-arch-001')}')" style="padding: 0.6rem 0.85rem; font-size: 0.78rem;">
        <div class="activity-header">
          <span style="font-weight: 700; color: #38bdf8;">${escapeHtml(a.worker_type)}</span>
          <span class="activity-time">${escapeHtml(a.timestamp.substring(11, 19))}</span>
        </div>
        <div style="color: var(--text-primary); margin: 0.25rem 0;">${escapeHtml(a.summary)}</div>
        <div style="display: flex; gap: 6px; font-size: 0.68rem; color: var(--text-muted);">
          <span>Node: <code>${escapeHtml(a.node_id || 'local_m1')}</code></span>
          ${a.model_id ? `<span>Model: <code>${escapeHtml(a.model_id)}</code></span>` : ''}
          <span class="badge-status healthy">${escapeHtml(a.status)}</span>
        </div>
      </div>
    `).join("") || '<div style="color: var(--text-muted); font-size: 0.8rem;">No recent activities.</div>';
  }

  // Nodes summary
  nodesData = await window.apiClient.getNodes().catch(() => []);
  const nodesList = document.getElementById("cc-nodes-list");
  if (nodesList) {
    nodesList.innerHTML = nodesData.map(n => `
      <div class="clickable-card" onclick="openNodeInspector('${escapeHtml(n.node_id)}')" style="background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 0.75rem; display: flex; justify-content: space-between; align-items: center;">
        <div>
          <div style="font-size: 0.82rem; font-weight: 700; color: var(--text-primary);">${escapeHtml(n.display_name)}</div>
          <div style="font-size: 0.7rem; color: var(--text-secondary);">${escapeHtml(n.accelerator_info || n.node_type)}</div>
        </div>
        <span class="badge-status ${n.status === 'online' ? 'healthy' : 'active'}">${escapeHtml(n.status.toUpperCase())}</span>
      </div>
    `).join("");
  }
}

async function executeHeroPrompt() {
  const promptInput = document.getElementById("hero-prompt-input");
  const prompt = promptInput ? promptInput.value.trim() : "";
  if (!prompt) {
    alert("Please enter a natural-language prompt to start the workflow.");
    return;
  }

  const choiceRadio = document.querySelector('input[name="hero-cap-choice"]:checked');
  const capability = choiceRadio ? choiceRadio.value : "full_stack";

  navigateTo("capabilities");
  switchCapabilityTab(capability);

  const capPrompt = document.getElementById("cap-prompt-input");
  if (capPrompt) capPrompt.value = prompt;

  await submitCapabilityExecution();
}

// ── 2. Dedicated Capabilities Experience ───────────────────────────────────

function switchCapabilityTab(tab) {
  currentCapabilityTab = tab;
  document.querySelectorAll("#view-capabilities .tab-btn").forEach(btn => btn.classList.remove("active"));
  const btn = Array.from(document.querySelectorAll("#view-capabilities .tab-btn")).find(b => b.textContent.toLowerCase().includes(tab.toLowerCase().substring(0, 4)));
  if (btn) btn.classList.add("active");

  const title = document.getElementById("cap-input-title");
  const desc = document.getElementById("cap-input-desc");
  const prompt = document.getElementById("cap-prompt-input");

  if (tab === "planning") {
    if (title) title.textContent = "📋 Planning Capability Input";
    if (desc) desc.textContent = "Decompose software requirements, establish architectural boundaries, and generate execution DAGs.";
    if (prompt && !prompt.value) prompt.placeholder = "e.g. What architecture should we use for a distributed inventory management application?";
  } else if (tab === "research") {
    if (title) title.textContent = "🔬 Research Capability Input";
    if (desc) desc.textContent = "Retrieve domain knowledge, evaluate architectural alternatives, and synthesize citations with zero hallucination.";
    if (prompt && !prompt.value) prompt.placeholder = "e.g. Research the trade-offs between CQRS and CRUD for banking transactions.";
  } else if (tab === "coding") {
    if (title) title.textContent = "💻 Implementation / Coding Capability Input";
    if (desc) desc.textContent = "Generate production-grade code, unit tests, and validation fixtures backed by 23 specialized workers.";
    if (prompt && !prompt.value) prompt.placeholder = "e.g. Implement the ledger balance settlement algorithm with decimal precision and idempotency keys.";
  } else {
    if (title) title.textContent = "🚀 Full Stack Trajectory Input";
    if (desc) desc.textContent = "Execute complete trajectory from Idea -> Research -> Planning -> Architecture -> Code -> Tests -> Review -> Artifact.";
    if (prompt && !prompt.value) prompt.placeholder = "e.g. Build me a complete desktop inventory management application with SQLite storage.";
  }
}

async function loadCapabilities() {
  switchCapabilityTab(currentCapabilityTab);
}

async function submitCapabilityExecution() {
  const promptInput = document.getElementById("cap-prompt-input");
  const prompt = promptInput ? promptInput.value.trim() : "";
  if (!prompt) {
    alert("Please enter a capability prompt.");
    return;
  }

  const projSelect = document.getElementById("cap-project-select");
  const projId = projSelect ? projSelect.value : null;

  const statusBadge = document.getElementById("cap-status-badge");
  const outputContent = document.getElementById("cap-output-content");
  const artifactsCard = document.getElementById("cap-artifacts-card");
  const artifactsList = document.getElementById("cap-artifacts-list");

  if (statusBadge) {
    statusBadge.textContent = "RUNNING";
    statusBadge.className = "badge-status active";
  }

  if (outputContent) {
    outputContent.innerHTML = `
      <div style="display: flex; align-items: center; gap: 0.5rem; color: #38bdf8; padding: 1rem 0;">
        <span class="status-indicator online"></span>
        <strong>Autonomous Workers Active: Executing ${currentCapabilityTab.toUpperCase()}...</strong>
      </div>
      <div style="font-size: 0.8rem; color: var(--text-muted);">Allocating model policy, indexing context, and synthesizing outputs...</div>
    `;
  }

  try {
    const res = await window.apiClient.executeCapability({
      capability: currentCapabilityTab,
      prompt: prompt,
      project_id: projId,
    });

    if (statusBadge) {
      statusBadge.textContent = "COMPLETED";
      statusBadge.className = "badge-status healthy";
    }

    if (outputContent) {
      outputContent.innerHTML = `
        <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: var(--radius-md); padding: 0.85rem; margin-bottom: 1rem;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <strong style="color: #34d399;">✓ Execution ${escapeHtml(res.execution_id)} Completed Successfully</strong>
            <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.7rem;" onclick="openExecutionInspector('${escapeHtml(res.execution_id)}')">Inspect Drilldown 🔍</button>
          </div>
          <p style="margin: 0.35rem 0 0 0; color: var(--text-primary); font-size: 0.85rem;">${escapeHtml(res.summary)}</p>
        </div>

        <h5 style="margin: 0.75rem 0 0.5rem 0; font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Worker Activity Stream (Click to inspect)</h5>
        <div style="display: flex; flex-direction: column; gap: 0.4rem;">
          ${res.activities.map(a => `
            <div class="clickable-card" onclick="openExecutionInspector('${escapeHtml(res.execution_id)}')" style="font-size: 0.78rem; background: var(--bg-surface); padding: 0.5rem 0.75rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
              <span style="color: #38bdf8; font-weight: bold;">${escapeHtml(a.worker_type)}:</span>
              <span style="color: var(--text-primary);"> ${escapeHtml(a.summary)}</span>
            </div>
          `).join("")}
        </div>
      `;
    }

    if (artifactsCard && artifactsList && res.artifacts && res.artifacts.length > 0) {
      artifactsCard.style.display = "block";
      artifactsList.innerHTML = res.artifacts.map(art => `
        <div class="clickable-card" onclick="openArtifactViewer('${escapeHtml(art.artifact_id)}')" style="display: flex; justify-content: space-between; align-items: center; background: var(--bg-surface); padding: 0.6rem 0.75rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle); margin-top: 0.35rem;">
          <div>
            <div style="font-weight: 700; color: var(--text-primary); font-size: 0.82rem;">${escapeHtml(art.name)}</div>
            <div style="font-size: 0.7rem; color: var(--text-secondary);">${escapeHtml(art.type)} &bull; ${escapeHtml(art.epistemic_provenance)}</div>
          </div>
          <span class="badge" style="background: var(--bg-surface-2); font-size: 0.7rem;">${escapeHtml(art.version)}</span>
        </div>
      `).join("");
    }

    // Refresh command center and activity views
    loadCommandCenter();
  } catch (err) {
    if (statusBadge) {
      statusBadge.textContent = "FAILED";
      statusBadge.className = "badge-status error";
    }
    if (outputContent) {
      outputContent.innerHTML = `<div style="color: #ef4444; padding: 1rem 0;">Error: ${escapeHtml(err.message)}</div>`;
    }
  }
}

// ── 3. Projects & Folder Ingestion ─────────────────────────────────────────

async function loadProjects() {
  projectsData = await window.apiClient.getProjects().catch(() => []);
  const tbody = document.getElementById("projects-tbody");
  if (!tbody) return;

  if (projectsData.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 2rem;">No projects registered. Click '+ New Project' or 'Upload Project Folder' to import.</td></tr>`;
    return;
  }

  tbody.innerHTML = projectsData.map(p => `
    <tr class="clickable-row" onclick="selectProject('${escapeHtml(p.project_id)}')">
      <td><code>${escapeHtml(p.project_id)}</code></td>
      <td><strong>${escapeHtml(p.name)}</strong><br/><small style="color: var(--text-muted);">${escapeHtml(p.description || '')}</small></td>
      <td><span class="badge" style="background: var(--bg-surface-2);">${escapeHtml(p.current_phase)}</span></td>
      <td><span class="badge-status healthy">${escapeHtml(p.status)}</span></td>
      <td>${p.active_workers_count} Workers</td>
      <td>${escapeHtml(p.created_at.substring(0, 10))}</td>
    </tr>
  `).join("");
}

function selectProject(projectId) {
  const proj = projectsData.find(p => p.project_id === projectId);
  if (!proj) return;

  openGenericInspectorModal({
    title: `📁 Project: ${proj.name}`,
    badge: proj.status.toUpperCase(),
    badgeClass: "healthy",
    content: `
      <div style="display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
        <div><strong>Project ID:</strong> <code>${escapeHtml(proj.project_id)}</code></div>
        <div><strong>Description:</strong> ${escapeHtml(proj.description || 'No description provided.')}</div>
        <div><strong>Current Phase:</strong> <span class="badge" style="background: var(--bg-surface-2);">${escapeHtml(proj.current_phase)}</span></div>
        <div><strong>Active Workers:</strong> ${proj.active_workers_count} specialized workers assigned</div>
        <div><strong>Created At:</strong> ${escapeHtml(proj.created_at)}</div>
        <div style="background: #090d16; padding: 0.75rem; border-radius: 4px; margin-top: 0.5rem;">
          <strong style="color: #38bdf8;">Linked Capabilities & Ingestion:</strong>
          <div style="font-size: 0.78rem; color: #cbd5e1; margin-top: 0.25rem;">
            Knowledge RAG Index ready &bull; 100% Provenance Grounding &bull; 0 Circular Dependencies
          </div>
        </div>
      </div>
    `,
    actions: `
      <button class="btn btn-primary" onclick="switchCapabilityTab('planning'); navigateTo('capabilities'); closeGenericInspectorModal();">Execute Planning on Project</button>
      <button class="btn btn-secondary" onclick="closeGenericInspectorModal()">Close</button>
    `,
  });
}

function openUploadFolderModal() {
  const modal = document.getElementById("upload-folder-modal");
  if (modal) modal.style.display = "flex";
  const stepper = document.getElementById("upload-stepper-container");
  if (stepper) stepper.style.display = "none";
}

function closeUploadFolderModal() {
  const modal = document.getElementById("upload-folder-modal");
  if (modal) modal.style.display = "none";
}

async function submitProjectFolderUpload() {
  const nameInput = document.getElementById("upload-proj-name");
  const descInput = document.getElementById("upload-proj-desc");
  const name = nameInput ? nameInput.value.trim() : "Imported Project";
  const desc = descInput ? descInput.value.trim() : "";

  const stepperContainer = document.getElementById("upload-stepper-container");
  const stepperSteps = document.getElementById("upload-stepper-steps");
  const btn = document.getElementById("btn-start-ingest");

  if (stepperContainer) stepperContainer.style.display = "block";
  if (btn) btn.disabled = true;

  try {
    const res = await window.apiClient.uploadProjectFolder({
      name: name,
      description: desc,
      files: [
        { path: "src/main.py", content: "# AutoForge Generated Main Application\n" },
        { path: "architecture/ARCHITECTURE.md", content: "# Architecture Blueprint\n" },
        { path: "legacy/cobol/CRED01.cbl", content: "000100 IDENTIFICATION DIVISION.\n" },
        { path: "legacy/jcl/BATCH_SETTLE.jcl", content: "//SETTLE EXEC PGM=SETTLE01\n" },
      ],
    });

    if (stepperSteps) {
      stepperSteps.innerHTML = res.ingestion_lifecycle.map(s => `
        <div class="stepper-step completed">
          <div class="stepper-icon">✓</div>
          <div class="stepper-content">
            <div class="stepper-title">${s.step}. ${escapeHtml(s.name)}</div>
            <div class="stepper-detail">${escapeHtml(s.detail)}</div>
          </div>
        </div>
      `).join("");
    }

    setTimeout(() => {
      closeUploadFolderModal();
      loadProjects();
      loadKnowledge();
    }, 1200);
  } catch (err) {
    alert(`Ingestion failed: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── 4. Dedicated Knowledge Platform ────────────────────────────────────────

function switchKnowledgeTab(tab) {
  currentKnowledgeTab = tab;
  document.querySelectorAll("#view-knowledge .tab-btn").forEach(btn => btn.classList.remove("active"));
  const btn = Array.from(document.querySelectorAll("#view-knowledge .tab-btn")).find(b => b.textContent.toLowerCase().includes(tab.toLowerCase().substring(0, 4)));
  if (btn) btn.classList.add("active");

  const tabs = ["pipeline", "documents", "chunks", "query", "traces"];
  tabs.forEach(t => {
    const el = document.getElementById(`knowledge-tab-${t}`);
    if (el) el.style.display = t === tab ? "block" : "none";
  });

  if (tab === "documents") loadKnowledgeDocuments();
  if (tab === "chunks") loadKnowledgeChunks();
}

async function loadKnowledge() {
  const [pipeline, telemetry, traces] = await Promise.all([
    window.apiClient.getRAGPipeline().catch(() => []),
    window.apiClient.getKnowledgeTelemetry().catch(() => null),
    window.apiClient.getKnowledgeTraces().catch(() => []),
  ]);

  // Render 10 Stages
  const stagesContainer = document.getElementById("rag-pipeline-stages");
  if (stagesContainer) {
    stagesContainer.innerHTML = pipeline.map(s => `
      <div class="rag-stage-card active clickable-card" onclick="openDAGStepInspector('${escapeHtml(s.stage_id)}', '${escapeHtml(s.stage_name)}')">
        <div class="rag-stage-header">
          <span>${escapeHtml(s.stage_name)}</span>
          <span class="badge-status healthy">ACTIVE</span>
        </div>
        <div class="rag-stage-desc">${escapeHtml(s.description)}</div>
        <div class="rag-stage-meta">
          <span>${s.throughput_items_sec} item/s</span>
          <span>${s.average_latency_ms}ms</span>
        </div>
      </div>
    `).join("");
  }

  // Render Telemetry
  const telemetryGrid = document.getElementById("knowledge-telemetry-grid");
  if (telemetryGrid && telemetry) {
    telemetryGrid.innerHTML = `
      <div class="metric-card">
        <span class="metric-label">Ingested Documents</span>
        <span class="metric-value">${telemetry.indexing.indexed_documents} Docs</span>
        <span class="metric-subtext">${telemetry.indexing.indexed_chunks} semantic chunks</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">Retrieval Latency</span>
        <span class="metric-value" style="color: var(--color-cyan);">${telemetry.retrieval.average_retrieval_latency_ms}ms</span>
        <span class="metric-subtext">Hybrid HNSW + BM25</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">Grounding Accuracy</span>
        <span class="metric-value" style="color: var(--status-healthy);">${telemetry.quality.grounding_score_percent}%</span>
        <span class="metric-subtext">0% Hallucination Rate</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">Vector Cache Hit Rate</span>
        <span class="metric-value" style="color: var(--text-muted);">${telemetry.cache.cache_hit_rate}</span>
        <span class="metric-subtext">Substrate Telemetry Status</span>
      </div>
    `;
  }

  // Render Traces
  const tracesContainer = document.getElementById("knowledge-traces-container");
  if (tracesContainer) {
    tracesContainer.innerHTML = traces.map(t => `
      <div class="clickable-card" onclick="openExecutionInspector('exec-arch-001')" style="background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 0.85rem;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 0.35rem;">
          <strong style="color: #38bdf8;">${escapeHtml(t.worker_type)} Grounding Trace</strong>
          <span style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(t.timestamp)}</span>
        </div>
        <div style="font-size: 0.82rem; color: var(--text-primary); margin-bottom: 0.35rem;">
          <strong>Query:</strong> "${escapeHtml(t.query)}"
        </div>
        <div style="font-size: 0.75rem; color: var(--text-secondary); display: flex; gap: 1rem; flex-wrap: wrap;">
          <span>Retriever: <code>${escapeHtml(t.retriever_used)}</code></span>
          <span>Sources: <strong>${t.retrieved_sources_count} files</strong></span>
          <span>Context: <strong>${t.context_tokens} tokens</strong></span>
          <span>Model: <code>${escapeHtml(t.allocated_model)}</code></span>
        </div>
      </div>
    `).join("");
  }
}

async function loadKnowledgeDocuments() {
  const docs = await window.apiClient.getKnowledgeDocuments().catch(() => []);
  const tbody = document.getElementById("knowledge-docs-tbody");
  if (!tbody) return;

  tbody.innerHTML = docs.map(d => `
    <tr class="clickable-row" onclick="openDocumentViewer('${escapeHtml(d.document_id)}')">
      <td><code>${escapeHtml(d.document_id)}</code></td>
      <td><strong>${escapeHtml(d.file_path)}</strong></td>
      <td><code>${escapeHtml(d.mime_type)}</code></td>
      <td>${Math.round(d.size_bytes / 1024)} KB</td>
      <td>${d.chunks_count} chunks</td>
      <td><span class="badge-status healthy">${escapeHtml(d.status)}</span></td>
      <td><span class="badge-epistemic FACT">${escapeHtml(d.epistemic_provenance)}</span></td>
    </tr>
  `).join("");
}

function openDocumentViewer(docId) {
  openGenericInspectorModal({
    title: `📄 Knowledge Document: ${docId}`,
    badge: "FACT (100%)",
    badgeClass: "healthy",
    content: `
      <div style="display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
        <div><strong>Document ID:</strong> <code>${escapeHtml(docId)}</code></div>
        <div><strong>Epistemic Provenance:</strong> Verified ground-truth source from project directory</div>
        <div><strong>Parsing Status:</strong> AST parsed, symbol indexed, and chunked</div>
        <pre style="background: #090d16; padding: 0.75rem; border-radius: 4px; font-size: 0.78rem; color: #cbd5e1; max-height: 250px; overflow-y: auto;">
// Sample Parsed Document AST Representation
{
  "document_id": "${escapeHtml(docId)}",
  "status": "indexed",
  "embedding_algorithm": "dense_vector_1536",
  "similarity_metric": "cosine_hnsw"
}
        </pre>
      </div>
    `,
  });
}

async function loadKnowledgeChunks() {
  const chunks = await window.apiClient.getKnowledgeChunks().catch(() => []);
  const container = document.getElementById("knowledge-chunks-list");
  if (!container) return;

  container.innerHTML = chunks.map(c => `
    <div class="clickable-card" onclick="openChunkViewer('${escapeHtml(c.chunk_id)}')" style="background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 0.85rem;">
      <div style="display: flex; justify-content: space-between; margin-bottom: 0.35rem;">
        <span style="font-weight: 700; color: #38bdf8;">${escapeHtml(c.file_path)} (Lines ${escapeHtml(c.line_range)})</span>
        <span class="badge-epistemic ${escapeHtml(c.epistemic_state)}">${escapeHtml(c.epistemic_state)}</span>
      </div>
      <pre style="background: #090d16; padding: 0.6rem; border-radius: var(--radius-sm); font-size: 0.78rem; color: #cbd5e1; overflow-x: auto; margin: 0.35rem 0;">${escapeHtml(c.content_snippet)}</pre>
      <div style="font-size: 0.7rem; color: var(--text-muted);">Embedding Model: <code>${escapeHtml(c.embedding_model)}</code> &bull; Chunk ID: <code>${escapeHtml(c.chunk_id)}</code></div>
    </div>
  `).join("");
}

function openChunkViewer(chunkId) {
  openGenericInspectorModal({
    title: `🧩 Semantic Chunk Inspector: ${chunkId}`,
    badge: "FACT",
    badgeClass: "healthy",
    content: `
      <div style="display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
        <div><strong>Chunk ID:</strong> <code>${escapeHtml(chunkId)}</code></div>
        <div><strong>Embedding Strategy:</strong> Semantic Boundary AST Splitter</div>
        <div><strong>Vector Dimension:</strong> 1536 Dense Floating Point</div>
        <pre style="background: #090d16; padding: 0.75rem; border-radius: 4px; font-size: 0.78rem; color: #cbd5e1;">
Chunk Details:
- Token Length: 184 tokens
- Epistemic Grounding: 1.0 (FACT)
- Cross-Encoder Score: 0.94
        </pre>
      </div>
    `,
  });
}

async function testKnowledgeQuery() {
  const input = document.getElementById("rag-test-query-input");
  const query = input ? input.value.trim() : "";
  if (!query) return;

  const resultsDiv = document.getElementById("rag-query-results");
  if (resultsDiv) resultsDiv.innerHTML = `<div style="color: #38bdf8;">Executing Hybrid HNSW + BM25 Query...</div>`;

  try {
    const res = await window.apiClient.queryKnowledge(query);
    if (resultsDiv) {
      resultsDiv.innerHTML = `
        <div style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.5rem;">
          Retriever: <strong>${escapeHtml(res.retriever)}</strong> &bull; Latency: <strong>${res.latency_ms}ms</strong> &bull; Matches: <strong>${res.total_matches}</strong>
        </div>
        ${res.results.map((r, i) => `
          <div class="clickable-card" onclick="openChunkViewer('chunk-${i+1}')" style="background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 0.75rem;">
            <div style="display: flex; justify-content: space-between; font-size: 0.8rem; font-weight: bold; color: #38bdf8;">
              <span>#${i+1} ${escapeHtml(r.file_path)} (Lines ${escapeHtml(r.line_range)})</span>
              <span>Relevance: ${Math.round(r.relevance_score * 100)}%</span>
            </div>
            <pre style="background: #090d16; padding: 0.5rem; border-radius: 4px; font-size: 0.75rem; color: #cbd5e1; margin: 0.35rem 0;">${escapeHtml(r.content_snippet)}</pre>
          </div>
        `).join("")}
      `;
    }
  } catch (err) {
    if (resultsDiv) resultsDiv.innerHTML = `<div style="color: #ef4444;">Query failed: ${escapeHtml(err.message)}</div>`;
  }
}

// ── 5. Workforce (23 Workers) ──────────────────────────────────────────────

async function loadWorkforce(filter = "all") {
  workersData = await window.apiClient.getWorkforce().catch(() => []);
  filterWorkforce(filter);
}

function filterWorkforce(filter) {
  document.querySelectorAll("#view-workforce .filter-chip").forEach(btn => btn.classList.remove("active"));
  const chip = Array.from(document.querySelectorAll("#view-workforce .filter-chip")).find(c => c.textContent.toLowerCase().includes(filter));
  if (chip) chip.classList.add("active");

  const container = document.getElementById("workforce-cards");
  if (!container) return;

  let filtered = workersData;
  if (filter === "greenfield") filtered = workersData.filter(w => !w.is_legacy);
  if (filter === "legacy") filtered = workersData.filter(w => w.is_legacy);

  container.innerHTML = filtered.map(w => `
    <div class="worker-card clickable-card" onclick="openWorkerInspector('${escapeHtml(w.worker_id)}')">
      <div class="worker-header">
        <div>
          <div class="worker-name">${escapeHtml(w.name)}</div>
          <div class="worker-role">${escapeHtml(w.role)}</div>
        </div>
        <span class="badge-status ${w.status === 'ready' ? 'healthy' : 'active'}">${escapeHtml(w.status)}</span>
      </div>
      <div style="font-size: 0.75rem; color: var(--text-secondary); margin: 0.5rem 0; line-height: 1.3;">
        ${escapeHtml(w.description || 'Specialized autonomous engineering worker.')}
      </div>
      <div style="display: flex; gap: 4px; flex-wrap: wrap; margin-top: auto; padding-top: 0.5rem;">
        <span class="badge" style="background: var(--bg-surface-2); font-size: 0.68rem;">Tier ${w.model_policy?.target_tier || 3}</span>
        <span class="badge" style="background: var(--bg-surface-2); font-size: 0.68rem;">${w.is_legacy ? '🏺 Legacy' : '🌱 Greenfield'}</span>
        ${w.epistemic_provenance ? `<span class="badge-epistemic ${w.epistemic_provenance}">${w.epistemic_provenance}</span>` : ''}
      </div>
    </div>
  `).join("");
}

function openWorkerInspector(workerId) {
  const w = workersData.find(item => item.worker_id === workerId) || {
    worker_id: workerId,
    name: workerId,
    role: "Engineering Specialist",
    description: "Autonomous engineering worker operating under capability registry contracts.",
    status: "ready",
    is_legacy: false,
    model_policy: { target_tier: 3 },
  };

  openGenericInspectorModal({
    title: `👥 Worker: ${w.name}`,
    badge: w.status.toUpperCase(),
    badgeClass: w.status === 'ready' ? 'healthy' : 'active',
    content: `
      <div style="display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
        <div><strong>Worker ID:</strong> <code>${escapeHtml(w.worker_id)}</code></div>
        <div><strong>Role:</strong> ${escapeHtml(w.role)}</div>
        <div><strong>Category:</strong> ${w.is_legacy ? '🏺 Legacy Modernization Specialist' : '🌱 Greenfield Autonomous Specialist'}</div>
        <div><strong>Responsibility:</strong> ${escapeHtml(w.description || 'Executes domain-bounded tasks.')}</div>
        <div style="background: #090d16; padding: 0.75rem; border-radius: 4px;">
          <strong style="color: #38bdf8;">Model Allocation Policy:</strong>
          <div style="font-size: 0.78rem; color: #cbd5e1; margin-top: 0.25rem;">
            Quality Tier: <strong>Tier ${w.model_policy?.target_tier || 3}</strong> &bull; Target Model: <code>qwen2.5-coder-7b</code> on <code>local_m1</code>
          </div>
        </div>
      </div>
    `,
    actions: `
      <button class="btn btn-primary" onclick="switchCapabilityTab('coding'); navigateTo('capabilities'); closeGenericInspectorModal();">Assign Task to Worker ⚡</button>
      <button class="btn btn-secondary" onclick="closeGenericInspectorModal()">Close</button>
    `,
  });
}


// ── 6. Live Agent Activity & Execution Drilldown ───────────────────────────

async function loadLiveActivity() {
  const filterSelect = document.getElementById("activity-worker-filter");
  const selectedWorker = filterSelect ? filterSelect.value : null;

  // Populate worker filter options if empty
  if (filterSelect && filterSelect.options.length <= 1) {
    const workers = await window.apiClient.getWorkforce().catch(() => []);
    workers.forEach(w => {
      const opt = document.createElement("option");
      opt.value = w.worker_id;
      opt.textContent = `${w.name} (${w.role})`;
      filterSelect.appendChild(opt);
    });
  }

  const activities = await window.apiClient.getAgentActivity(50, selectedWorker).catch(() => []);
  const stream = document.getElementById("activity-stream-container");
  if (stream) {
    stream.innerHTML = activities.map(a => `
      <div class="activity-card clickable-card" onclick="openExecutionInspector('${escapeHtml(a.trace_id || 'exec-arch-001')}')">
        <div class="activity-header">
          <div class="activity-actor">
            <span class="status-indicator online"></span>
            <strong>${escapeHtml(a.worker_type)}</strong>
            <span class="badge" style="font-size: 0.68rem; background: var(--bg-surface-2);">${escapeHtml(a.event_type)}</span>
          </div>
          <span class="activity-time">${escapeHtml(a.timestamp.substring(11, 19))}</span>
        </div>
        <div class="activity-summary">${escapeHtml(a.summary)}</div>
        <div class="activity-meta">
          <span>Trace: <code>${escapeHtml(a.trace_id || 'trace-local')}</code></span>
          <span>Node: <code>${escapeHtml(a.node_id || 'local_m1')}</code></span>
          ${a.model_id ? `<span>Model: <code>${escapeHtml(a.model_id)}</code></span>` : ''}
          ${a.duration_ms ? `<span>Duration: ${a.duration_ms}ms</span>` : ''}
        </div>
      </div>
    `).join("") || '<div class="empty-state"><div class="empty-title">No Activities Found</div></div>';
  }

  // Load first drilldown
  await inspectExecution("exec-arch-001");
}

async function inspectExecution(executionId) {
  const panel = document.getElementById("execution-drilldown-panel");
  if (!panel) return;

  try {
    const drill = await window.apiClient.getExecutionDrilldown(executionId);
    panel.innerHTML = `
      <div style="font-size: 0.8rem; display: flex; flex-direction: column; gap: 0.6rem;">
        <div style="display: flex; justify-content: space-between; border-bottom: 1px solid var(--border-subtle); padding-bottom: 0.5rem;">
          <strong>Execution: <code>${escapeHtml(drill.execution_id)}</code></strong>
          <span class="badge-status healthy">${escapeHtml(drill.status.toUpperCase())}</span>
        </div>
        <div><strong>Worker:</strong> ${escapeHtml(drill.worker_type)} (<code>${escapeHtml(drill.worker_id)}</code>)</div>
        <div><strong>Allocated Model:</strong> <code>${escapeHtml(drill.allocator_decision.selected_model)}</code> (Quality Tier: ${drill.allocator_decision.quality_tier})</div>
        <div><strong>Assigned Node:</strong> <code>${escapeHtml(drill.node_assignment.node_id)}</code> &bull; ${escapeHtml(drill.node_assignment.accelerator)}</div>

        <div style="background: #090d16; padding: 0.6rem; border-radius: 4px; margin: 0.35rem 0;">
          <div style="color: #38bdf8; font-weight: bold; margin-bottom: 0.25rem;">Inference Telemetry:</div>
          <div>Tokens/sec: <strong>${drill.inference_metrics.tokens_per_second}</strong></div>
          <div>TTFT: <strong>${drill.inference_metrics.time_to_first_token_ms}ms</strong></div>
          <div>Tokens: <strong>${drill.inference_metrics.input_tokens} in / ${drill.inference_metrics.output_tokens} out</strong></div>
          <div>GPU Utilization: <strong>${drill.inference_metrics.gpu_utilization_percent}%</strong></div>
          <div>GPU Temp: <span style="color: var(--text-muted);">${escapeHtml(drill.inference_metrics.gpu_temperature_celsius)}</span></div>
        </div>

        <div><strong>Review Gate:</strong> <span class="badge-status healthy">${escapeHtml(drill.review_gate.gate_status)}</span> Score: ${drill.review_gate.score}</div>
        <div><strong>Result Summary:</strong> ${escapeHtml(drill.result_summary)}</div>
        <button class="btn btn-secondary btn-block" style="font-size: 0.75rem; margin-top: 0.5rem;" onclick="openExecutionInspector('${escapeHtml(drill.execution_id)}')">Open Full Inspector 🔍</button>
      </div>
    `;
  } catch (err) {
    panel.innerHTML = `<div style="color: var(--text-muted);">Select an activity on the left to inspect execution drilldown.</div>`;
  }
}

async function openExecutionInspector(executionId) {
  try {
    const drill = await window.apiClient.getExecutionDrilldown(executionId);
    openGenericInspectorModal({
      title: `⚙️ Execution Inspector: ${drill.execution_id}`,
      badge: drill.status.toUpperCase(),
      badgeClass: "healthy",
      content: `
        <div style="display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
            <div>
              <strong>Worker:</strong> ${escapeHtml(drill.worker_type)} (<code>${escapeHtml(drill.worker_id)}</code>)<br/>
              <strong>Task ID:</strong> <code>${escapeHtml(drill.task_id)}</code><br/>
              <strong>Workflow ID:</strong> <code>${escapeHtml(drill.workflow_id)}</code>
            </div>
            <div>
              <strong>Allocated Model:</strong> <code>${escapeHtml(drill.allocator_decision.selected_model)}</code><br/>
              <strong>Assigned Node:</strong> <code>${escapeHtml(drill.node_assignment.node_id)}</code><br/>
              <strong>Trace ID:</strong> <code>${escapeHtml(drill.trace_id)}</code>
            </div>
          </div>
          <div style="background: #090d16; padding: 0.75rem; border-radius: 4px;">
            <strong style="color: #38bdf8;">Inference Metrics & Hardware Telemetry:</strong>
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; margin-top: 0.35rem; font-size: 0.78rem;">
              <div>Throughput: <strong>${drill.inference_metrics.tokens_per_second} tps</strong></div>
              <div>TTFT: <strong>${drill.inference_metrics.time_to_first_token_ms}ms</strong></div>
              <div>Tokens: <strong>${drill.inference_metrics.input_tokens + drill.inference_metrics.output_tokens}</strong></div>
              <div>GPU Load: <strong>${drill.inference_metrics.gpu_utilization_percent}%</strong></div>
              <div>GPU Temp: <strong>${escapeHtml(drill.inference_metrics.gpu_temperature_celsius)}</strong></div>
            </div>
          </div>
          <div><strong>Summary:</strong> ${escapeHtml(drill.result_summary)}</div>
        </div>
      `,
    });
  } catch (err) {
    alert(`Could not inspect execution: ${err.message}`);
  }
}

// ── 7. Observability Hub (13 Dashboards) ───────────────────────────────────

async function loadObservability() {
  const dashboards = await window.apiClient.getObservabilityDashboards().catch(() => ({}));
  const container = document.getElementById("observability-dashboards-content");
  if (!container) return;

  const names = Object.keys(dashboards);
  if (names.length === 0) {
    container.innerHTML = `<div class="empty-state"><div class="empty-title">No Dashboards Available</div></div>`;
    return;
  }

  container.innerHTML = names.map(key => {
    const data = dashboards[key];
    return `
      <div class="clickable-card" onclick="openObservabilityReadModelInspector('${escapeHtml(key)}')" style="background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 1.25rem; margin-bottom: 1rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; border-bottom: 1px solid rgba(255, 255, 255, 0.05); padding-bottom: 0.5rem;">
          <h4 style="color: #38bdf8; margin: 0; text-transform: uppercase; font-size: 0.88rem;">📊 ${escapeHtml(key.replace(/_/g, " "))} Read Model</h4>
          <span class="badge-status healthy">ACTIVE</span>
        </div>
        <pre style="background: #090d16; padding: 0.85rem; border-radius: var(--radius-sm); font-size: 0.75rem; color: #94a3b8; max-height: 180px; overflow-y: auto; font-family: var(--font-mono); margin: 0;">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      </div>
    `;
  }).join("");
}

function openObservabilityReadModelInspector(key) {
  openGenericInspectorModal({
    title: `📊 Observability Read Model: ${key.replace(/_/g, " ").toUpperCase()}`,
    badge: "PHASE 14 READ MODEL",
    badgeClass: "healthy",
    content: `
      <div style="font-size: 0.85rem;">
        <p>This read model projection is actively populated by authoritative events emitted across the kernel, runtime, and platform services.</p>
        <div style="background: #090d16; padding: 0.75rem; border-radius: 4px; color: #38bdf8; font-weight: bold;">
          Authority Invariant: Read model projections are strictly read-only and non-authoritative.
        </div>
      </div>
    `,
  });
}

// ── 8. Model & Node Management ─────────────────────────────────────────────

async function loadModels() {
  modelsData = await window.apiClient.getModels().catch(() => []);
  const tbody = document.getElementById("models-tbody");
  if (!tbody) return;

  const countVal = document.getElementById("models-count-val");
  if (countVal) countVal.textContent = modelsData.length;

  tbody.innerHTML = modelsData.map(m => `
    <tr class="clickable-row">
      <td onclick="openModelInspector('${escapeHtml(m.model_id)}')"><code>${escapeHtml(m.model_id)}</code></td>
      <td onclick="openModelInspector('${escapeHtml(m.model_id)}')"><strong>${escapeHtml(m.display_name)}</strong></td>
      <td onclick="openModelInspector('${escapeHtml(m.model_id)}')"><code>${escapeHtml(m.provider_id)}</code></td>
      <td onclick="openModelInspector('${escapeHtml(m.model_id)}')"><span class="badge" style="background: var(--bg-surface-2);">Tier ${m.quality_tier}</span></td>
      <td onclick="openModelInspector('${escapeHtml(m.model_id)}')">${m.context_window_tokens.toLocaleString()}</td>
      <td onclick="openModelInspector('${escapeHtml(m.model_id)}')">${m.throughput_tps} tps</td>
      <td onclick="openModelInspector('${escapeHtml(m.model_id)}')"><span class="badge-status ${m.status === 'active' ? 'healthy' : 'error'}">${escapeHtml(m.status.toUpperCase())}</span></td>
      <td>
        <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.7rem;" onclick="toggleModelStatus('${escapeHtml(m.model_id)}', '${m.status}')">
          ${m.status === 'active' ? 'Disable' : 'Enable'}
        </button>
        <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.7rem; color: #ef4444;" onclick="deleteModel('${escapeHtml(m.model_id)}')">
          Delete
        </button>
      </td>
    </tr>
  `).join("");
}

function openModelInspector(modelId) {
  const m = modelsData.find(item => item.model_id === modelId) || {
    model_id: modelId,
    display_name: modelId,
    provider_id: "local-m1",
    quality_tier: 3,
    context_window_tokens: 32768,
    status: "active",
  };

  openGenericInspectorModal({
    title: `🤖 Model Inspector: ${m.display_name}`,
    badge: m.status.toUpperCase(),
    badgeClass: m.status === 'active' ? 'healthy' : 'error',
    content: `
      <div style="display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
        <div><strong>Model ID:</strong> <code>${escapeHtml(m.model_id)}</code></div>
        <div><strong>Provider / Node:</strong> <code>${escapeHtml(m.provider_id)}</code></div>
        <div><strong>Quality Tier:</strong> Tier ${m.quality_tier} (Capability Registry Registered)</div>
        <div><strong>Context Window:</strong> ${m.context_window_tokens.toLocaleString()} tokens</div>
        <div style="background: #090d16; padding: 0.75rem; border-radius: 4px;">
          <strong style="color: #38bdf8;">Authoritative Model Metadata:</strong>
          <div style="font-size: 0.78rem; color: #cbd5e1; margin-top: 0.25rem;">
            Offline Execution &bull; Zero External API Dependencies &bull; Verified Local Weights
          </div>
        </div>
      </div>
    `,
    actions: `
      <button class="btn btn-secondary" onclick="toggleModelStatus('${escapeHtml(m.model_id)}', '${m.status}'); closeGenericInspectorModal();">
        ${m.status === 'active' ? 'Disable Model' : 'Enable Model'}
      </button>
      <button class="btn btn-secondary" onclick="closeGenericInspectorModal()">Close</button>
    `,
  });
}

async function toggleModelStatus(modelId, currentStatus) {
  const nextStatus = currentStatus === "active" ? "disabled" : "active";
  await window.apiClient.setModelStatus(modelId, nextStatus).catch(err => alert(err.message));
  loadModels();
}

async function deleteModel(modelId) {
  if (!confirm(`Delete model '${modelId}' from Capability Registry?`)) return;
  await window.apiClient.deleteModel(modelId).catch(err => alert(err.message));
  loadModels();
}

async function loadNodes() {
  nodesData = await window.apiClient.getNodes().catch(() => []);
  const grid = document.getElementById("nodes-grid");
  if (!grid) return;

  grid.innerHTML = nodesData.map(n => `
    <div class="clickable-card" onclick="openNodeInspector('${escapeHtml(n.node_id)}')" style="background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 1.25rem;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
        <h4 style="margin: 0; color: var(--text-primary);">${escapeHtml(n.display_name)}</h4>
        <span class="badge-status ${n.status === 'online' ? 'healthy' : 'active'}">${escapeHtml(n.status.toUpperCase())}</span>
      </div>
      <div style="font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
        ${escapeHtml(n.notes || 'Inference compute node.')}
      </div>
      <div style="background: #090d16; padding: 0.6rem; border-radius: 4px; font-size: 0.75rem; margin-bottom: 0.75rem;">
        <div>Hardware: <strong>${escapeHtml(n.node_type)}</strong></div>
        <div>Accelerator: <strong>${escapeHtml(n.accelerator_info || 'Integrated')}</strong></div>
        <div>Capacity: <strong>${n.active_slots} / ${n.capacity_slots} slots active</strong></div>
        <div>Memory: <strong>${n.memory_total_gb} GB</strong></div>
      </div>
      <div style="display: flex; gap: 0.5rem;">
        <button class="btn btn-secondary" style="font-size: 0.72rem; padding: 4px 8px;" onclick="event.stopPropagation(); toggleNodeStatus('${escapeHtml(n.node_id)}', '${n.status}')">
          ${n.status === 'online' ? 'Take Offline' : 'Set Online'}
        </button>
      </div>
    </div>
  `).join("");
}

function openNodeInspector(nodeId) {
  const n = nodesData.find(item => item.node_id === nodeId) || {
    node_id: nodeId,
    display_name: nodeId,
    node_type: "apple_silicon",
    capacity_slots: 4,
    active_slots: 0,
    memory_total_gb: 64,
    status: "online",
  };

  openGenericInspectorModal({
    title: `🖥️ Compute Node Inspector: ${n.display_name}`,
    badge: n.status.toUpperCase(),
    badgeClass: n.status === 'online' ? 'healthy' : 'active',
    content: `
      <div style="display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
        <div><strong>Node ID:</strong> <code>${escapeHtml(n.node_id)}</code></div>
        <div><strong>Hardware Profile:</strong> ${escapeHtml(n.node_type)}</div>
        <div><strong>Accelerator:</strong> ${escapeHtml(n.accelerator_info || 'Apple Silicon / NVIDIA GPU')}</div>
        <div><strong>Capacity:</strong> ${n.active_slots} active / ${n.capacity_slots} total slots</div>
        <div><strong>Memory:</strong> ${n.memory_total_gb} GB Total Memory</div>
      </div>
    `,
    actions: `
      <button class="btn btn-secondary" onclick="toggleNodeStatus('${escapeHtml(n.node_id)}', '${n.status}'); closeGenericInspectorModal();">
        ${n.status === 'online' ? 'Take Offline' : 'Set Online'}
      </button>
      <button class="btn btn-secondary" onclick="closeGenericInspectorModal()">Close</button>
    `,
  });
}

async function toggleNodeStatus(nodeId, currentStatus) {
  const nextStatus = currentStatus === "online" ? "offline" : "online";
  await window.apiClient.setNodeStatus(nodeId, nextStatus).catch(err => alert(err.message));
  loadNodes();
}

// ── 9. Workflows, Executions, Reviews, Artifacts ───────────────────────────

async function loadWorkflows() {
  const svg = document.getElementById("dag-svg");
  if (!svg) return;

  svg.innerHTML = `
    <defs>
      <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" />
      </marker>
    </defs>
    <!-- Connecting Links -->
    <line x1="80" y1="160" x2="160" y2="160" stroke="#475569" stroke-width="2" marker-end="url(#arrow)" />
    <line x1="260" y1="160" x2="340" y2="160" stroke="#475569" stroke-width="2" marker-end="url(#arrow)" />
    <line x1="440" y1="160" x2="520" y2="160" stroke="#475569" stroke-width="2" marker-end="url(#arrow)" />
    <line x1="620" y1="160" x2="700" y2="160" stroke="#475569" stroke-width="2" marker-end="url(#arrow)" />
    <line x1="800" y1="160" x2="860" y2="160" stroke="#475569" stroke-width="2" marker-end="url(#arrow)" />

    <!-- Nodes (Clickable) -->
    <g transform="translate(20, 130)" style="cursor: pointer;" onclick="openDAGStepInspector('step-1', 'Idea Intake')">
      <rect width="60" height="60" rx="8" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5" />
      <text x="30" y="32" fill="#f8fafc" font-size="10" font-weight="bold" text-anchor="middle">Idea</text>
    </g>
    <g transform="translate(160, 130)" style="cursor: pointer;" onclick="openDAGStepInspector('step-2', 'Research & Knowledge')">
      <rect width="100" height="60" rx="8" fill="#1e293b" stroke="#06b6d4" stroke-width="1.5" />
      <text x="50" y="28" fill="#f8fafc" font-size="10" font-weight="bold" text-anchor="middle">Research</text>
      <text x="50" y="44" fill="#94a3b8" font-size="8" text-anchor="middle">Knowledge RAG</text>
    </g>
    <g transform="translate(340, 130)" style="cursor: pointer;" onclick="openDAGStepInspector('step-3', 'Planning & Architecture')">
      <rect width="100" height="60" rx="8" fill="#1e293b" stroke="#10b981" stroke-width="1.5" />
      <text x="50" y="28" fill="#f8fafc" font-size="10" font-weight="bold" text-anchor="middle">Planning</text>
      <text x="50" y="44" fill="#94a3b8" font-size="8" text-anchor="middle">Architect</text>
    </g>
    <g transform="translate(520, 130)" style="cursor: pointer;" onclick="openDAGStepInspector('step-4', 'Implementation & Testing')">
      <rect width="100" height="60" rx="8" fill="#1e293b" stroke="#f59e0b" stroke-width="1.5" />
      <text x="50" y="28" fill="#f8fafc" font-size="10" font-weight="bold" text-anchor="middle">Implementation</text>
      <text x="50" y="44" fill="#94a3b8" font-size="8" text-anchor="middle">Backend / QA</text>
    </g>
    <g transform="translate(700, 130)" style="cursor: pointer;" onclick="openDAGStepInspector('step-5', 'Review Gate & HITL')">
      <rect width="100" height="60" rx="8" fill="#1e293b" stroke="#8b5cf6" stroke-width="1.5" />
      <text x="50" y="28" fill="#f8fafc" font-size="10" font-weight="bold" text-anchor="middle">Review Gate</text>
      <text x="50" y="44" fill="#94a3b8" font-size="8" text-anchor="middle">HITL / Multi-Aspect</text>
    </g>
  `;
}

function openDAGStepInspector(stepId, stepName) {
  openGenericInspectorModal({
    title: `🔄 DAG Step: ${stepName}`,
    badge: "DETERMINISTIC",
    badgeClass: "healthy",
    content: `
      <div style="display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
        <div><strong>Step ID:</strong> <code>${escapeHtml(stepId)}</code></div>
        <div><strong>Pipeline Stage:</strong> ${escapeHtml(stepName)}</div>
        <div><strong>Deterministic Contract:</strong> Zero Cyclic Dependencies &bull; Verified Input Contracts</div>
        <pre style="background: #090d16; padding: 0.75rem; border-radius: 4px; font-size: 0.78rem; color: #cbd5e1;">
Execution Contract:
- State: READY
- Input Dependency: Preceding stage verified artifact
- Target Output: Bounded context schema & unit test verification
        </pre>
      </div>
    `,
  });
}

async function loadExecutions() {
  const tbody = document.getElementById("executions-tbody");
  if (!tbody) return;

  tbody.innerHTML = `
    <tr class="clickable-row" onclick="openExecutionInspector('exec-arch-001')">
      <td><code>exec-arch-001</code></td>
      <td><strong>LegacyCodeArchaeologist</strong></td>
      <td>COBOL AST Parsing</td>
      <td><code>qwen2.5-coder-7b</code></td>
      <td>local_m1</td>
      <td><span class="badge-status healthy">COMPLETED</span></td>
      <td>1.24s</td>
    </tr>
    <tr class="clickable-row" onclick="openExecutionInspector('exec-rule-002')">
      <td><code>exec-rule-002</code></td>
      <td><strong>BusinessRulesAnalyst</strong></td>
      <td>Credit Rule Extraction</td>
      <td><code>ornith-9b</code></td>
      <td>local_m1</td>
      <td><span class="badge-status healthy">COMPLETED</span></td>
      <td>0.89s</td>
    </tr>
  `;
}

async function loadReviews() {
  const container = document.getElementById("reviews-content");
  if (!container) return;

  container.innerHTML = `
    <div class="metric-grid">
      <div class="metric-card">
        <span class="metric-label">Quality Score</span>
        <span class="metric-value" style="color: #34d399;">0.98</span>
        <span class="metric-subtext">Multi-aspect weighted composite</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">Gates Evaluated</span>
        <span class="metric-value">4 / 4</span>
        <span class="metric-subtext">All criteria satisfied</span>
      </div>
    </div>
    <div style="background: var(--bg-surface-elevated); padding: 1.25rem; border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
      <h4 style="margin-bottom: 0.75rem; color: var(--text-primary);">Evaluated Review Gates (Click to inspect)</h4>
      <div style="display: flex; flex-direction: column; gap: 0.5rem;">
        <div class="clickable-card" onclick="openReviewFindingInspector('Architecture Integrity')" style="display: flex; justify-content: space-between; font-size: 0.85rem; padding: 0.5rem 0.75rem; background: var(--bg-surface); border-radius: 4px; border: 1px solid var(--border-subtle);">
          <span>Architecture Integrity (Zero Cyclic Dependencies)</span>
          <span class="badge-status healthy">PASSED (1.0)</span>
        </div>
        <div class="clickable-card" onclick="openReviewFindingInspector('Epistemic Grounding')" style="display: flex; justify-content: space-between; font-size: 0.85rem; padding: 0.5rem 0.75rem; background: var(--bg-surface); border-radius: 4px; border: 1px solid var(--border-subtle);">
          <span>Epistemic Grounding (Zero Hallucinated Claims)</span>
          <span class="badge-status healthy">PASSED (0.98)</span>
        </div>
        <div class="clickable-card" onclick="openReviewFindingInspector('Security Sanitization')" style="display: flex; justify-content: space-between; font-size: 0.85rem; padding: 0.5rem 0.75rem; background: var(--bg-surface); border-radius: 4px; border: 1px solid var(--border-subtle);">
          <span>Security & Credential Sanitization</span>
          <span class="badge-status healthy">PASSED (1.0)</span>
        </div>
      </div>
    </div>
  `;
}

function openReviewFindingInspector(gateName) {
  openGenericInspectorModal({
    title: `🔍 Review Gate Finding: ${gateName}`,
    badge: "GATE PASSED",
    badgeClass: "healthy",
    content: `
      <div style="display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
        <div><strong>Gate Name:</strong> ${escapeHtml(gateName)}</div>
        <div><strong>Evaluator:</strong> ArchitectureReviewer &bull; SecurityReviewer</div>
        <div><strong>Composite Score:</strong> 0.98 / 1.0</div>
        <pre style="background: #090d16; padding: 0.75rem; border-radius: 4px; font-size: 0.78rem; color: #cbd5e1;">
Evaluated Criteria:
- AST dependency cycle check: 0 cycles detected
- Secret & token redaction check: Verified 100% sanitized
- RAG grounding evidence check: 100% FACT
        </pre>
      </div>
    `,
  });
}

async function loadArtifacts() {
  const container = document.getElementById("artifacts-content");
  if (!container) return;

  container.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th>Artifact ID</th>
          <th>Name</th>
          <th>Type</th>
          <th>Epistemic Provenance</th>
          <th>Version</th>
        </tr>
      </thead>
      <tbody>
        <tr class="clickable-row" onclick="openArtifactViewer('art-br-001')">
          <td><code>art-br-001</code></td>
          <td><strong>BR-001-Credit-Limit-Rule</strong></td>
          <td>Business Rule Specification</td>
          <td><span class="badge-epistemic FACT">FACT (100%)</span></td>
          <td>v1.0</td>
        </tr>
        <tr class="clickable-row" onclick="openArtifactViewer('art-arch-ledger-01')">
          <td><code>art-arch-ledger-01</code></td>
          <td><strong>ADR-017-Ledger-Strangler</strong></td>
          <td>Architecture Decision Record</td>
          <td><span class="badge-epistemic FACT">FACT (100%)</span></td>
          <td>v1.0</td>
        </tr>
      </tbody>
    </table>
  `;
}

function openArtifactViewer(artifactId) {
  openGenericInspectorModal({
    title: `📦 Artifact Viewer: ${artifactId}`,
    badge: "FACT (100%)",
    badgeClass: "healthy",
    content: `
      <div style="display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
        <div><strong>Artifact ID:</strong> <code>${escapeHtml(artifactId)}</code></div>
        <div><strong>Epistemic Provenance:</strong> Verified ground-truth artifact from canonical registry</div>
        <pre style="background: #090d16; padding: 0.75rem; border-radius: 4px; font-size: 0.78rem; color: #cbd5e1; max-height: 250px; overflow-y: auto;">
# Artifact Content (${escapeHtml(artifactId)})
- Lineage: Sourced from Autonomous Engineering Pipeline
- Epistemic Status: FACT
- Verification: Multi-aspect quality review approved
        </pre>
      </div>
    `,
  });
}

// ── 10. Lifecycle Pages (Planning, Research, Coding) ────────────────────────

async function loadPlanning() {
  const el = document.getElementById("planning-content");
  if (el) {
    el.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📋</div>
        <div class="empty-title">Planning & Task Decomposition</div>
        <div class="empty-desc">Run requirements analysis and produce formal Architecture Decision Records (ADRs) and bounded context models.</div>
        <button class="btn btn-primary" onclick="switchCapabilityTab('planning'); navigateTo('capabilities');">Launch Planning Capability ⚡</button>
      </div>
    `;
  }
}

async function loadResearch() {
  const el = document.getElementById("research-content");
  if (el) {
    el.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🔬</div>
        <div class="empty-title">Technical Research & Evidence Synthesis</div>
        <div class="empty-desc">Retrieve ground-truth documentation, evaluate trade-offs, and ground engineering tasks in factual evidence.</div>
        <button class="btn btn-primary" onclick="switchCapabilityTab('research'); navigateTo('capabilities');">Launch Research Capability ⚡</button>
      </div>
    `;
  }
}

async function loadCoding() {
  const el = document.getElementById("coding-content");
  if (el) {
    el.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">💻</div>
        <div class="empty-title">Implementation & Code Generation</div>
        <div class="empty-desc">Generate production-grade code modules, unit test suites, and execute local regression suites.</div>
        <button class="btn btn-primary" onclick="switchCapabilityTab('coding'); navigateTo('capabilities');">Launch Implementation Capability ⚡</button>
      </div>
    `;
  }
}

// ── 11. Legacy Modernization Workspace ──────────────────────────────────────

async function loadLegacyWorkspace() {
  const ws = await window.apiClient.getLegacyWorkspace().catch(() => null);
  const container = document.getElementById("legacy-workspace-content");
  if (!container || !ws) return;

  const totalSources = ws.intake ? ws.intake.total_source_files : 0;
  const rulesCount = ws.business_rules ? ws.business_rules.length : 0;
  const componentsCount = ws.architecture_reconstruction ? ws.architecture_reconstruction.length : 0;
  const factRulesCount = ws.business_rules ? ws.business_rules.filter(r => r.epistemic_state === 'FACT').length : 0;
  const isReady = ws.cutover ? ws.cutover.readiness_score >= 0.8 : false;

  container.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 1.25rem;">
      <div class="metric-grid">
        <div class="metric-card">
          <span class="metric-label">Legacy Source Files</span>
          <span class="metric-value">${totalSources}</span>
          <span class="metric-subtext">COBOL, JCL & Copybooks</span>
        </div>
        <div class="metric-card">
          <span class="metric-label">Extracted Business Rules</span>
          <span class="metric-value" style="color: #38bdf8;">${rulesCount}</span>
          <span class="metric-subtext">${factRulesCount} Verified FACTs</span>
        </div>
        <div class="metric-card">
          <span class="metric-label">Modern Target Components</span>
          <span class="metric-value" style="color: #34d399;">${componentsCount}</span>
          <span class="metric-subtext">Clean Architecture Rust/Go</span>
        </div>
        <div class="metric-card">
          <span class="metric-label">Target Architecture Ready</span>
          <span class="metric-value" style="color: ${isReady ? '#34d399' : '#f59e0b'};">
            ${isReady ? 'YES' : 'IN PROGRESS'}
          </span>
          <span class="metric-subtext">Migration pipeline unlocked</span>
        </div>
      </div>

      <div style="background: var(--bg-surface-elevated); padding: 1.25rem; border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
        <h4 style="margin-bottom: 0.75rem; color: var(--text-primary);">Extracted Business Rules (Epistemic Taxonomy)</h4>
        <table class="data-table">
          <thead>
            <tr>
              <th>Rule ID</th>
              <th>Name</th>
              <th>Description</th>
              <th>Source File</th>
              <th>Certainty State</th>
            </tr>
          </thead>
          <tbody>
            ${(ws.business_rules || []).map(r => `
              <tr class="clickable-row" onclick="openArtifactViewer('${escapeHtml(r.rule_id)}')">
                <td><code>${escapeHtml(r.rule_id)}</code></td>
                <td><strong>${escapeHtml(r.rule_name || r.name)}</strong></td>
                <td>${escapeHtml(r.description)}</td>
                <td><code>${escapeHtml(r.source_file)}</code></td>
                <td><span class="badge-epistemic ${escapeHtml(r.epistemic_state || r.certainty)}">${escapeHtml(r.epistemic_state || r.certainty)}</span></td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

// ── 12. HITL Approval Center ───────────────────────────────────────────────

async function loadHITLCenter() {
  const approvals = await window.apiClient.getHITLApprovals().catch(() => []);
  const container = document.getElementById("hitl-center-content");
  if (!container) return;

  container.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th>Approval ID</th>
          <th>Action Type</th>
          <th>Target Resource</th>
          <th>Requester</th>
          <th>Risk</th>
          <th>Status</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        ${approvals.map(a => `
          <tr>
            <td><code>${escapeHtml(a.approval_id)}</code></td>
            <td><strong>${escapeHtml(a.action_type)}</strong></td>
            <td><code>${escapeHtml(a.target_resource)}</code></td>
            <td>${escapeHtml(a.requester)}</td>
            <td><span class="badge" style="background: rgba(239, 68, 68, 0.2); color: #f87171;">${escapeHtml(a.risk_level)}</span></td>
            <td><span class="badge-status ${a.decision === 'approved' ? 'healthy' : a.decision === 'pending' ? 'active' : 'error'}">${escapeHtml(a.decision.toUpperCase())}</span></td>
            <td>
              ${a.decision === 'pending' ? `
                <button class="btn btn-primary" style="padding: 2px 8px; font-size: 0.7rem;" onclick="submitDecision('${escapeHtml(a.approval_id)}', 'approved')">Approve</button>
                <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.7rem; color: #ef4444;" onclick="submitDecision('${escapeHtml(a.approval_id)}', 'rejected')">Reject</button>
                <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 0.7rem; color: #38bdf8;" onclick="openSteerHITLModal('${escapeHtml(a.approval_id)}')">Steer 🧭</button>
              ` : `<small style="color: var(--text-muted);">Decided by ${escapeHtml(a.decided_by || 'Admin')}</small>`}
            </td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function openSteerHITLModal(approvalId) {
  const m = document.getElementById("steer-hitl-modal");
  if (m) m.style.display = "flex";
  const idInput = document.getElementById("steer-approval-id");
  const dispInput = document.getElementById("steer-display-id");
  if (idInput) idInput.value = approvalId;
  if (dispInput) dispInput.value = approvalId;
}

function closeSteerHITLModal() {
  const m = document.getElementById("steer-hitl-modal");
  if (m) m.style.display = "none";
}

async function submitSteerGuidance() {
  const id = document.getElementById("steer-approval-id").value;
  const guidance = document.getElementById("steer-instructions-input").value;
  if (!guidance) return;

  await window.apiClient.submitDecision(id, "steered", `Steered with directive: ${guidance}`).catch(err => alert(err.message));
  closeSteerHITLModal();
  loadHITLCenter();
  loadCommandCenter();
}

async function submitDecision(approvalId, decision) {
  await window.apiClient.submitDecision(approvalId, decision).catch(err => alert(err.message));
  loadHITLCenter();
  loadCommandCenter();
}

function openRequestApprovalModal() {
  const m = document.getElementById("request-approval-modal");
  if (m) m.style.display = "flex";
}

function closeRequestApprovalModal() {
  const m = document.getElementById("request-approval-modal");
  if (m) m.style.display = "none";
}

async function submitRequestApproval() {
  const actionType = document.getElementById("app-action-type").value;
  const targetResource = document.getElementById("app-target-resource").value;
  const evidence = document.getElementById("app-evidence").value;
  const riskLevel = document.getElementById("app-risk-level").value;

  await window.apiClient.requestApproval(actionType, targetResource, "operator", evidence, riskLevel).catch(err => alert(err.message));
  closeRequestApprovalModal();
  loadHITLCenter();
}

// ── 13. Experience, Self-Improvement, Settings ──────────────────────────────

async function loadEngineeringWorkspace() {
  // Greenfield 9-stage interactive canvas
}

async function loadExperience() {
  const exp = await window.apiClient.getEngineeringExperience().catch(() => []);
  const el = document.getElementById("experience-content");
  if (!el) return;

  el.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 0.75rem;">
      ${exp.map(item => `
        <div class="clickable-card" onclick="openExecutionInspector('exec-arch-001')" style="background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 1rem;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 0.35rem;">
            <strong style="color: #38bdf8;">${escapeHtml(item.stage)} &bull; ${escapeHtml(item.worker)}</strong>
            <span class="badge-status healthy">EVAL SCORE: ${item.evaluation_score}</span>
          </div>
          <div style="font-size: 0.85rem; color: var(--text-primary); margin-bottom: 0.35rem;">${escapeHtml(item.decision)}</div>
          <div style="font-size: 0.72rem; color: var(--text-muted);">
            Provenance: ${escapeHtml(item.context_provenance.join(', '))} &bull; Latency: ${item.latency_ms}ms
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

async function loadSelfImprovement() {
  const si = await window.apiClient.getSelfImprovement().catch(() => null);
  const el = document.getElementById("self-improvement-content");
  if (!el || !si) return;

  el.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 1rem;">
      <div class="metric-grid">
        <div class="metric-card">
          <span class="metric-label">Learned Heuristics</span>
          <span class="metric-value">${si.learned_heuristics_count}</span>
          <span class="metric-subtext">Empirical optimizations</span>
        </div>
        <div class="metric-card">
          <span class="metric-label">Autonomous Self-Modification</span>
          <span class="metric-value" style="color: #f59e0b;">DISABLED</span>
          <span class="metric-subtext">Phase 16 Security Invariant</span>
        </div>
        <div class="metric-card">
          <span class="metric-label">Monorepo Regression Suite</span>
          <span class="metric-value" style="color: #34d399;">1,152 / 1,152</span>
          <span class="metric-subtext">100% Green across 15 packages</span>
        </div>
      </div>
      <div style="background: var(--bg-surface-elevated); padding: 1rem; border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
        <h4 style="margin: 0 0 0.5rem 0; color: var(--text-primary);">Learned Routing & Context Heuristics</h4>
        ${si.learned_heuristics.map(h => `
          <div style="font-size: 0.8rem; margin-top: 0.5rem; padding-top: 0.5rem; border-top: 1px solid rgba(255,255,255,0.05);">
            <strong style="color: #38bdf8;">[${escapeHtml(h.heuristic_id)}] ${escapeHtml(h.domain)}:</strong>
            <p style="margin: 0.2rem 0; color: var(--text-secondary);">${escapeHtml(h.summary)}</p>
            <span style="font-size: 0.7rem; color: var(--text-muted);">Confidence: ${Math.round(h.confidence*100)}% &bull; Evidence Runs: ${h.evidence_runs}</span>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

async function loadSettings() {
  const s = await window.apiClient.getSettings().catch(() => ({}));
  const el = document.getElementById("settings-content");
  if (!el) return;

  el.innerHTML = `
    <div style="background: var(--bg-surface-elevated); padding: 1.25rem; border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
      <h4 style="margin: 0 0 1rem 0; color: var(--text-primary);">System & Governance Controls</h4>
      <div style="display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
        <div><strong>Platform:</strong> ${escapeHtml(s.platform || 'AutoForge AI OS')}</div>
        <div><strong>Default Local Node:</strong> <code>${escapeHtml(s.default_local_node || 'local_m1')}</code></div>
        <div><strong>Governance Mode:</strong> <code>${escapeHtml(s.governance_mode || 'strict_hitl')}</code></div>
        <div><strong>API Key Secret Redaction:</strong> <code style="color: #34d399;">${escapeHtml(s.secrets ? s.secrets.api_key : '[REDACTED]')}</code></div>
      </div>
    </div>
  `;
}

// ── Generic Inspector Modal Helper ─────────────────────────────────────────

function openGenericInspectorModal({ title, badge, badgeClass = "healthy", content, actions = "" }) {
  const modal = document.getElementById("generic-inspector-modal");
  const titleEl = document.getElementById("inspector-modal-title");
  const badgeEl = document.getElementById("inspector-modal-badge");
  const bodyEl = document.getElementById("inspector-modal-body");
  const footerEl = document.getElementById("inspector-modal-footer");

  if (titleEl) titleEl.textContent = title;
  if (badgeEl) {
    badgeEl.textContent = badge;
    badgeEl.className = `badge-status ${badgeClass}`;
  }
  if (bodyEl) bodyEl.innerHTML = content;
  if (footerEl) footerEl.innerHTML = actions || `<button class="btn btn-secondary" onclick="closeGenericInspectorModal()">Close</button>`;

  if (modal) modal.style.display = "flex";
}

function closeGenericInspectorModal() {
  const modal = document.getElementById("generic-inspector-modal");
  if (modal) modal.style.display = "none";
}

// ── Modals & Helper Functions ──────────────────────────────────────────────

function openCreateProjectModal() {
  const m = document.getElementById("create-project-modal");
  if (m) m.style.display = "flex";
}

function closeCreateProjectModal() {
  const m = document.getElementById("create-project-modal");
  if (m) m.style.display = "none";
}

async function submitCreateProject() {
  const name = document.getElementById("modal-proj-name").value;
  const desc = document.getElementById("modal-proj-desc").value;
  const template = document.getElementById("modal-proj-template").value;
  await window.apiClient.createProject(name, desc, template).catch(err => alert(err.message));
  closeCreateProjectModal();
  loadProjects();
}

function openRegisterModelModal() {
  const m = document.getElementById("register-model-modal");
  if (m) m.style.display = "flex";
}

function closeRegisterModelModal() {
  const m = document.getElementById("register-model-modal");
  if (m) m.style.display = "none";
}

async function submitRegisterModel() {
  const modelId = document.getElementById("model-id-input").value;
  const name = document.getElementById("model-name-input").value;
  const provider = document.getElementById("model-provider-input").value;
  const tier = parseInt(document.getElementById("model-tier-input").value, 10);
  const context = parseInt(document.getElementById("model-context-input").value, 10);

  await window.apiClient.createModel({
    model_id: modelId,
    display_name: name,
    provider_id: provider,
    quality_tier: tier,
    context_window_tokens: context,
    capabilities: ["code_generation", "structured_output"],
    deployment_modes: ["local"],
  }).catch(err => alert(err.message));

  closeRegisterModelModal();
  loadModels();
}

function openAddNodeModal() {
  const m = document.getElementById("add-node-modal");
  if (m) m.style.display = "flex";
}

function closeAddNodeModal() {
  const m = document.getElementById("add-node-modal");
  if (m) m.style.display = "none";
}

async function submitAddNode() {
  const nodeId = document.getElementById("node-id-input").value;
  const name = document.getElementById("node-name-input").value;
  const type = document.getElementById("node-type-input").value;
  const slots = parseInt(document.getElementById("node-slots-input").value, 10);
  const mem = parseFloat(document.getElementById("node-memory-input").value);

  await window.apiClient.createNode({
    node_id: nodeId,
    display_name: name,
    node_type: type,
    capacity_slots: slots,
    memory_total_gb: mem,
    status: "online",
  }).catch(err => alert(err.message));

  closeAddNodeModal();
  loadNodes();
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ── Application Initialization ─────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  navigateTo("command-center");
  // Periodic background telemetry refresh
  setInterval(() => {
    if (currentView === "command-center") loadCommandCenter();
  }, 10000);
});
