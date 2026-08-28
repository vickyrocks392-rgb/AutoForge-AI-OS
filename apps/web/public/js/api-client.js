/**
 * API Client for AutoForge AI OS Product Experience.
 * Connects to the local-first REST API boundary.
 */

class AutoForgeApiClient {
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl;
  }

  async _request(path, options = {}) {
    const url = `${this.baseUrl}${path}`;
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    };

    try {
      const res = await fetch(url, { ...options, headers });
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${res.status}: ${res.statusText}`);
      }
      return await res.json();
    } catch (err) {
      console.error(`API Error on ${path}:`, err);
      throw err;
    }
  }

  // System
  getSystemStatus() {
    return this._request("/api/system/status");
  }

  setWorkspaceMode(mode) {
    return this._request("/api/system/mode", {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
  }

  // Projects
  getProjects() {
    return this._request("/api/projects");
  }

  createProject(name, description, template = "greenfield") {
    return this._request("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, description, template }),
    });
  }

  // Workforce
  getWorkforce() {
    return this._request("/api/workforce");
  }

  // Workflows
  getWorkflows() {
    return this._request("/api/workflows");
  }

  // Executions
  getExecutions() {
    return this._request("/api/executions");
  }

  // Reviews
  getReviews() {
    return this._request("/api/reviews");
  }

  // Artifacts
  getArtifacts() {
    return this._request("/api/artifacts");
  }

  // Legacy Modernization
  getLegacyWorkspace() {
    return this._request("/api/legacy");
  }

  // Infrastructure
  getInfrastructure() {
    return this._request("/api/infrastructure");
  }

  // HITL Approvals
  getHITLApprovals() {
    return this._request("/api/hitl/approvals");
  }

  requestApproval(action_type, target_resource, requester, evidence, risk_level = "high") {
    return this._request("/api/hitl/approvals", {
      method: "POST",
      body: JSON.stringify({ action_type, target_resource, requester, evidence, risk_level }),
    });
  }

  submitDecision(approval_id, decision, actor_id = "operator_admin_01", feedback = "") {
    return this._request("/api/hitl/decision", {
      method: "POST",
      body: JSON.stringify({ approval_id, decision, actor_id, feedback }),
    });
  }

  // Agent Activity & Live Execution Drilldown
  getAgentActivity(limit = 50, worker_id = null) {
    const params = new URLSearchParams({ limit });
    if (worker_id) params.append("worker_id", worker_id);
    return this._request(`/api/activity?${params.toString()}`);
  }

  getExecutionDrilldown(executionId = "exec-arch-001") {
    return this._request(`/api/executions/drilldown?execution_id=${encodeURIComponent(executionId)}`);
  }

  // Capabilities
  executeCapability(payload) {
    return this._request("/api/capabilities/execute", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  // Project Folder Upload
  uploadProjectFolder(payload) {
    return this._request("/api/projects/upload", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  // Model Management
  getModels() {
    return this._request("/api/models");
  }

  createModel(modelData) {
    return this._request("/api/models", {
      method: "POST",
      body: JSON.stringify(modelData),
    });
  }

  setModelStatus(modelId, status) {
    return this._request(`/api/models/${encodeURIComponent(modelId)}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
  }

  deleteModel(modelId) {
    return this._request(`/api/models/${encodeURIComponent(modelId)}`, {
      method: "DELETE",
    });
  }

  // Node Management
  getNodes() {
    return this._request("/api/nodes");
  }

  createNode(nodeData) {
    return this._request("/api/nodes", {
      method: "POST",
      body: JSON.stringify(nodeData),
    });
  }

  setNodeStatus(nodeId, status) {
    return this._request(`/api/nodes/${encodeURIComponent(nodeId)}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
  }

  deleteNode(nodeId) {
    return this._request(`/api/nodes/${encodeURIComponent(nodeId)}`, {
      method: "DELETE",
    });
  }

  // Knowledge & RAG Platform
  getRAGPipeline() {
    return this._request("/api/knowledge/pipeline");
  }

  getKnowledgeDocuments() {
    return this._request("/api/knowledge/documents");
  }

  getKnowledgeChunks(documentId = null) {
    const q = documentId ? `?document_id=${encodeURIComponent(documentId)}` : "";
    return this._request(`/api/knowledge/chunks${q}`);
  }

  queryKnowledge(query, topK = 5) {
    return this._request("/api/knowledge/query", {
      method: "POST",
      body: JSON.stringify({ query, top_k: topK }),
    });
  }

  getKnowledgeTelemetry() {
    return this._request("/api/knowledge/telemetry");
  }

  getKnowledgeTraces() {
    return this._request("/api/knowledge/traces");
  }

  // Observability & ADR-004 Read Models
  getObservabilityDashboards() {
    return this._request("/api/observability/dashboards");
  }

  getEngineeringExperience() {
    return this._request("/api/experience");
  }

  // Self Improvement
  getSelfImprovement() {
    return this._request("/api/self-improvement");
  }

  // Settings
  getSettings() {
    return this._request("/api/settings");
  }
}

window.apiClient = new AutoForgeApiClient();

