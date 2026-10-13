/**
 * PolicyDesk Knowledge Assistant — Frontend Application Logic
 * Pure Vanilla JavaScript implementation with zero external runtime dependencies.
 */

document.addEventListener("DOMContentLoaded", () => {
  // Navigation elements
  const navButtons = document.querySelectorAll(".nav-item");
  const views = document.querySelectorAll(".workspace-view");

  // Chat elements
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const chatThread = document.getElementById("chat-thread");
  const chatEmptyState = document.getElementById("chat-empty-state");
  const btnResetChat = document.getElementById("btn-reset-chat");
  const btnSend = document.getElementById("btn-send");
  const sampleChips = document.querySelectorAll(".chip-btn");

  // Document elements
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const btnBrowseFiles = document.getElementById("btn-browse-files");
  const uploadProgressBox = document.getElementById("upload-progress-box");
  const uploadStatusText = document.getElementById("upload-status-text");
  const docsTableBody = document.getElementById("docs-table-body");
  const docsCountLabel = document.getElementById("docs-count-label");
  const sidebarDocCount = document.getElementById("sidebar-doc-count");
  const btnRefreshDocs = document.getElementById("btn-refresh-docs");

  // Evaluation elements
  const btnRunEval = document.getElementById("btn-run-eval");
  const evalTableBody = document.getElementById("eval-table-body");
  const evalAccVal = document.getElementById("eval-acc-val");
  const evalGroundVal = document.getElementById("eval-ground-val");
  const evalCiteVal = document.getElementById("eval-cite-val");
  const evalAbstainVal = document.getElementById("eval-abstain-val");
  const evalAccSub = document.getElementById("eval-acc-sub");

  // Settings & Diagnostics elements
  const stVectorStore = document.getElementById("st-vector-store");
  const stCollection = document.getElementById("st-collection");
  const stEmbeddingModel = document.getElementById("st-embedding-model");
  const stLlmProvider = document.getElementById("st-llm-provider");
  const stLlmModel = document.getElementById("st-llm-model");
  const stDataDir = document.getElementById("st-data-dir");
  const diagVectorDetail = document.getElementById("diag-vector-detail");
  const diagLlmDetail = document.getElementById("diag-llm-detail");
  const diagLlmBadge = document.getElementById("diag-llm-badge");
  const btnResetKb = document.getElementById("btn-reset-kb");

  // Evidence Modal elements
  const evidenceModal = document.getElementById("evidence-modal");
  const modalFilename = document.getElementById("modal-filename");
  const modalLocation = document.getElementById("modal-location");
  const modalScore = document.getElementById("modal-score");
  const modalVersion = document.getElementById("modal-version");
  const modalPassageText = document.getElementById("modal-passage-text");
  const btnCloseModal = document.getElementById("btn-close-modal");
  const btnModalDismiss = document.getElementById("btn-modal-dismiss");

  // State
  let documents = [];
  let currentEvidenceItems = [];

  // ── Navigation Handler ───────────────────────────────────────────────────
  navButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetView = btn.getAttribute("data-view");
      navButtons.forEach((b) => b.classList.remove("active"));
      views.forEach((v) => v.classList.remove("active"));

      btn.classList.add("active");
      const activeSection = document.getElementById(targetView);
      if (activeSection) activeSection.classList.add("active");

      if (targetView === "docs-view") {
        fetchDocuments();
      } else if (targetView === "settings-view") {
        fetchHealthAndSettings();
      }
    });
  });

  // ── Chat Functions ───────────────────────────────────────────────────────
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      chatForm.dispatchEvent(new Event("submit"));
    }
  });

  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = chatInput.value.trim();
    if (!query) return;

    chatInput.value = "";
    if (chatEmptyState) {
      chatEmptyState.style.display = "none";
    }

    appendUserMessage(query);
    const loadingBubble = appendAssistantLoading();

    try {
      const response = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query, top_k: 5 }),
      });

      if (!response.ok) {
        throw new Error(`Server returned error ${response.status}: ${await response.text()}`);
      }

      const data = await response.json();
      removeElement(loadingBubble);
      appendAssistantResponse(data);
    } catch (err) {
      removeElement(loadingBubble);
      appendErrorMessage(`Failed to process question: ${err.message}`);
    }
  });

  sampleChips.forEach((chip) => {
    chip.addEventListener("click", () => {
      const q = chip.getAttribute("data-query");
      chatInput.value = q;
      chatForm.dispatchEvent(new Event("submit"));
    });
  });

  btnResetChat.addEventListener("click", () => {
    chatThread.innerHTML = "";
    if (chatEmptyState) {
      chatEmptyState.style.display = "block";
      chatThread.appendChild(chatEmptyState);
    }
  });

  function appendUserMessage(text) {
    const msgDiv = document.createElement("div");
    msgDiv.className = "chat-message user";
    msgDiv.innerHTML = `
      <div class="chat-avatar">U</div>
      <div class="chat-bubble">
        <p>${escapeHtml(text)}</p>
      </div>
    `;
    chatThread.appendChild(msgDiv);
    scrollToBottom();
  }

  function appendAssistantLoading() {
    const msgDiv = document.createElement("div");
    msgDiv.className = "chat-message assistant";
    msgDiv.innerHTML = `
      <div class="chat-avatar">PD</div>
      <div class="chat-bubble">
        <div style="display:flex; align-items:center; gap:8px; color:var(--text-muted); font-size:0.86rem;">
          <span class="status-dot healthy" style="animation: pulseProgress 0.8s infinite alternate;"></span>
          <span>Searching persistent knowledge base and synthesizing grounded response...</span>
        </div>
      </div>
    `;
    chatThread.appendChild(msgDiv);
    scrollToBottom();
    return msgDiv;
  }

  function appendAssistantResponse(data) {
    const msgDiv = document.createElement("div");
    msgDiv.className = "chat-message assistant";

    let conflictHtml = "";
    if (data.conflict && data.conflict.has_conflict) {
      conflictHtml = `
        <div class="callout-amber">
          <strong>⚠️ Policy Conflict Detected:</strong>
          <div>${escapeHtml(data.conflict.summary)}</div>
          <div style="margin-top:4px; font-size:0.82rem;">
            <div>• <strong>Current Policy:</strong> ${escapeHtml(data.conflict.active_policy || "")}</div>
            <div>• <strong>Archived/Superseded:</strong> ${escapeHtml(data.conflict.superseded_policy || "")}</div>
          </div>
        </div>
      `;
    }

    let abstentionHtml = "";
    if (data.abstained) {
      abstentionHtml = `
        <div class="callout-abstention">
          <strong>ℹ️ Out of Scope / Missing Information:</strong>
          <span>The requested information is not documented in approved PolicyDesk files. The assistant declined to generate unverified claims.</span>
        </div>
      `;
    }

    let citationsHtml = "";
    if (data.citations && data.citations.length > 0) {
      const pills = data.citations
        .map((cit, idx) => {
          const loc = cit.page ? `p.${cit.page}` : cit.line_range;
          const scorePercent = Math.round(cit.score * 100);
          return `
            <button class="citation-pill" data-cit-idx="${idx}" title="Inspect verified passage in ${escapeHtml(cit.filename)}">
              <span>📄 ${escapeHtml(cit.filename)} (${loc})</span>
              <span style="opacity:0.75; font-size:0.7rem;">${scorePercent}%</span>
            </button>
          `;
        })
        .join("");

      citationsHtml = `
        <div class="citations-strip">
          <span class="citations-label">Sources:</span>
          ${pills}
        </div>
      `;
    }

    const formattedAnswer = renderMarkdown(data.answer);

    msgDiv.innerHTML = `
      <div class="chat-avatar">PD</div>
      <div class="chat-bubble">
        ${conflictHtml}
        ${abstentionHtml}
        <div class="assistant-text">${formattedAnswer}</div>
        ${citationsHtml}
        <div style="margin-top:10px; font-size:0.7rem; color:var(--text-muted); display:flex; justify-content:space-between;">
          <span>Latency: ${data.latency_ms}ms | Model: ${escapeHtml(data.model_used)}</span>
          <span>Grounding: ${Math.round(data.grounding_score * 100)}%</span>
        </div>
      </div>
    `;

    chatThread.appendChild(msgDiv);

    // Bind citation click events to open Evidence Modal
    const citationBtns = msgDiv.querySelectorAll(".citation-pill");
    citationBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.getAttribute("data-cit-idx"), 10);
        if (data.citations && data.citations[idx]) {
          openEvidenceModal(data.citations[idx]);
        }
      });
    });

    scrollToBottom();
  }

  function appendErrorMessage(text) {
    const msgDiv = document.createElement("div");
    msgDiv.className = "chat-message assistant";
    msgDiv.innerHTML = `
      <div class="chat-avatar" style="background:#EF4444;">!</div>
      <div class="chat-bubble" style="border-color: rgba(239, 68, 68, 0.4);">
        <p style="color:#FCA5A5;">${escapeHtml(text)}</p>
      </div>
    `;
    chatThread.appendChild(msgDiv);
    scrollToBottom();
  }

  function scrollToBottom() {
    chatThread.scrollTop = chatThread.scrollHeight;
  }

  function removeElement(el) {
    if (el && el.parentNode) {
      el.parentNode.removeChild(el);
    }
  }

  // ── Evidence Modal Logic ─────────────────────────────────────────────────
  function openEvidenceModal(citation) {
    modalFilename.textContent = citation.filename;
    modalLocation.textContent = citation.page ? `Page ${citation.page} (${citation.line_range})` : citation.line_range;
    modalScore.textContent = `${Math.round(citation.score * 100)}% Similarity`;
    modalVersion.textContent = citation.version ? `v${citation.version} (${citation.effective_date || "Active"})` : "Standard";
    modalPassageText.textContent = citation.passage;
    evidenceModal.style.display = "flex";
  }

  function closeEvidenceModal() {
    evidenceModal.style.display = "none";
  }

  btnCloseModal.addEventListener("click", closeEvidenceModal);
  btnModalDismiss.addEventListener("click", closeEvidenceModal);
  evidenceModal.addEventListener("click", (e) => {
    if (e.target === evidenceModal) closeEvidenceModal();
  });

  // ── Document Management Functions ─────────────────────────────────────────
  async function fetchDocuments() {
    try {
      const res = await fetch("/api/documents");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      documents = data.documents || [];
      renderDocumentsTable(documents, data.total_chunks);
      if (sidebarDocCount) sidebarDocCount.textContent = documents.length;
    } catch (err) {
      docsTableBody.innerHTML = `<tr><td colspan="7" class="badge-danger" style="padding:14px;">Failed to load documents: ${err.message}</td></tr>`;
    }
  }

  function renderDocumentsTable(docs, totalChunks) {
    if (docsCountLabel) {
      docsCountLabel.textContent = `${docs.length} documents indexed (${totalChunks} searchable chunks)`;
    }

    if (!docs || docs.length === 0) {
      docsTableBody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:32px; color:var(--text-muted);">No documents ingested yet. Upload a PDF, Markdown, or plain-text document above.</td></tr>`;
      return;
    }

    docsTableBody.innerHTML = docs
      .map((doc) => {
        const sizeKb = Math.round(doc.size_bytes / 1024);
        const formatBadge = `<span class="badge badge-${doc.format}">${doc.format.toUpperCase()}</span>`;
        const statusBadge = `<span class="badge badge-success">INDEXED</span>`;
        const verLabel = doc.version ? `v${doc.version}` : "1.0";

        return `
          <tr id="doc-row-${doc.doc_id}">
            <td><strong>${escapeHtml(doc.filename)}</strong></td>
            <td>${formatBadge}</td>
            <td><span style="font-family:var(--font-mono); font-size:0.8rem;">${verLabel}</span></td>
            <td>${sizeKb} KB</td>
            <td><strong>${doc.chunks_count}</strong></td>
            <td>${statusBadge}</td>
            <td>
              <button class="btn btn-danger btn-sm btn-delete-doc" data-doc-id="${doc.doc_id}" style="padding:4px 10px; font-size:0.75rem;">
                Remove
              </button>
            </td>
          </tr>
        `;
      })
      .join("");

    const deleteButtons = docsTableBody.querySelectorAll(".btn-delete-doc");
    deleteButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const did = btn.getAttribute("data-doc-id");
        deleteDocument(did);
      });
    });
  }

  async function deleteDocument(docId) {
    if (!confirm(`Are you sure you want to remove document '${docId}' and purge all its retrievable chunks?`)) {
      return;
    }
    try {
      const res = await fetch(`/api/documents/${docId}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await res.text());
      fetchDocuments();
    } catch (err) {
      alert(`Deletion failed: ${err.message}`);
    }
  }

  btnBrowseFiles.addEventListener("click", () => fileInput.click());
  btnRefreshDocs.addEventListener("click", fetchDocuments);

  fileInput.addEventListener("change", (e) => {
    if (fileInput.files.length > 0) {
      handleFileUpload(fileInput.files[0]);
    }
  });

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  });

  async function handleFileUpload(file) {
    uploadProgressBox.style.display = "block";
    uploadStatusText.textContent = `Uploading and indexing '${file.name}'...`;

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/documents/upload", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(errData.detail || "Upload error");
      }

      const outcome = await res.json();
      uploadStatusText.textContent = outcome.message;
      setTimeout(() => {
        uploadProgressBox.style.display = "none";
        fetchDocuments();
      }, 1200);
    } catch (err) {
      alert(`Upload failed: ${err.message}`);
      uploadProgressBox.style.display = "none";
    }
  }

  // ── Evaluation Workspace Functions ────────────────────────────────────────
  btnRunEval.addEventListener("click", async () => {
    btnRunEval.disabled = true;
    btnRunEval.textContent = "Running Benchmark Suite...";
    evalTableBody.innerHTML = `<tr><td colspan="7" class="table-loading">Evaluating test cases against live vector store...</td></tr>`;

    try {
      const res = await fetch("/api/evaluation/run", { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      const m = data.metrics;
      evalAccVal.textContent = `${Math.round(m.accuracy * 100)}%`;
      evalAccSub.textContent = `${m.passed_cases} of ${m.total_cases} passed`;
      evalGroundVal.textContent = `${Math.round(m.grounding_rate * 100)}%`;
      evalCiteVal.textContent = `${Math.round(m.citation_accuracy * 100)}%`;
      evalAbstainVal.textContent = `${Math.round(m.abstention_accuracy * 100)}%`;

      renderEvaluationTable(data.case_results || []);
    } catch (err) {
      alert(`Evaluation failed: ${err.message}`);
    } finally {
      btnRunEval.disabled = false;
      btnRunEval.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Run Benchmark Suite`;
    }
  });

  function renderEvaluationTable(cases) {
    if (!cases || cases.length === 0) {
      evalTableBody.innerHTML = `<tr><td colspan="7">No test cases returned.</td></tr>`;
      return;
    }

    evalTableBody.innerHTML = cases
      .map((c) => {
        const passBadge = c.passed
          ? `<span class="badge badge-success">PASS</span>`
          : `<span class="badge badge-danger">FAIL</span>`;
        const isAbstain = c.abstained ? `<span class="badge badge-warning">ABSTAINED</span>` : "Answered";
        const citeCount = c.citations ? c.citations.length : 0;
        const answerSnippet = c.answer ? escapeHtml(c.answer.substring(0, 110)) + "..." : "—";

        return `
          <tr>
            <td><span style="font-family:var(--font-mono); font-size:0.75rem;">${escapeHtml(c.id)}</span></td>
            <td><span class="badge badge-md">${escapeHtml(c.category)}</span></td>
            <td><strong>${escapeHtml(c.query)}</strong></td>
            <td>${c.expected_abstain ? "Abstain (Out of scope)" : "Grounded answer"}</td>
            <td>${answerSnippet}</td>
            <td>${citeCount} citation(s)</td>
            <td>${passBadge}</td>
          </tr>
        `;
      })
      .join("");
  }

  // ── Settings & Diagnostics Functions ──────────────────────────────────────
  async function fetchHealthAndSettings() {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const h = await res.json();

      stVectorStore.textContent = h.vector_store;
      stCollection.textContent = h.collection_name;
      stEmbeddingModel.textContent = `${h.embedding_model} (${h.embedding_dimensions} dims)`;
      stLlmProvider.textContent = h.generation_provider;
      stLlmModel.textContent = h.generation_model;
      stDataDir.textContent = h.data_directory;

      if (h.components) {
        if (h.components.vector_store) diagVectorDetail.textContent = h.components.vector_store.details;
        if (h.components.generation_runtime) {
          diagLlmDetail.textContent = h.components.generation_runtime.details;
          if (!h.generation_available) {
            diagLlmBadge.className = "badge badge-warning";
            diagLlmBadge.textContent = "Offline (Extractive Fallback)";
          } else {
            diagLlmBadge.className = "badge badge-success";
            diagLlmBadge.textContent = "Online";
          }
        }
      }
    } catch (err) {
      console.warn("Could not fetch health:", err);
    }
  }

  btnResetKb.addEventListener("click", async () => {
    if (!confirm("Are you sure you want to RESET the PolicyDesk knowledge base? All indexed documents and vector chunks will be wiped!")) {
      return;
    }
    try {
      const res = await fetch("/api/reset", { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      alert("Knowledge base reset completed successfully.");
      fetchDocuments();
      fetchHealthAndSettings();
    } catch (err) {
      alert(`Reset error: ${err.message}`);
    }
  });

  // ── Utilities ─────────────────────────────────────────────────────────────
  function escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function renderMarkdown(md) {
    if (!md) return "";
    let html = escapeHtml(md);
    // Bolding **text**
    html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    // Bullet points
    html = html.replace(/^\s*-\s+(.*)$/gm, "<li>$1</li>");
    html = html.replace(/(<li>.*<\/li>)/s, "<ul style='margin: 8px 0 8px 20px;'>$1</ul>");
    // Line breaks
    html = html.replace(/\n\n/g, "<br><br>");
    return html;
  }

  // Initial load
  fetchDocuments();
  fetchHealthAndSettings();
});
