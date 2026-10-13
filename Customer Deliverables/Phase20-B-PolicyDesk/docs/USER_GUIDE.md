# PolicyDesk Knowledge Assistant — Staff User Guide

Welcome to the PolicyDesk Knowledge Assistant! This tool allows PolicyDesk consulting staff to query approved company documents, operating procedures, and consulting rate cards in plain English.

---

## 1. Asking Questions (Knowledge Chat)

1. Navigate to the **Knowledge Chat** view from the left sidebar.
2. Enter your question in the composer box at the bottom.
3. Examples of queries you can ask:
   - *"What is our standard hourly rate for a Senior Consultant?"*
   - *"What is the deadline for submitting weekly timesheets?"*
   - *"What is the daily meal per diem allowance on business trips?"*
   - *"What are the password requirements under our security policy?"*
4. Press **Enter** or click the send button.

---

## 2. Inspecting Citations & Evidence

- Every answer cites the documents and passages used to construct the response.
- At the bottom of each assistant answer, click on any **Source Pill** (e.g., `📄 consulting_rate_card.pdf (p.1)`).
- The **Evidence Modal** will display:
  - Exact source document name.
  - Page number (for PDF documents) or line range (for Markdown/Text).
  - Relevance score.
  - The exact text passage extracted from the document.

---

## 3. Policy Conflicts & Version Ambiguity

- When multiple documents discuss the same policy with differing terms (such as the 2024 Travel Policy vs. the superseding 2026 Travel Policy), the system displays an amber **Policy Conflict Notice** above the answer.
- The assistant clearly explains which policy is active and which is archived/superseded.

---

## 4. Unanswerable Questions & Missing Evidence

- If your query cannot be answered by approved PolicyDesk documentation, the assistant will **explicitly abstain** and state that the information is missing.
- It will never fabricate policies, numbers, or rules.

---

## 5. Document Management

1. Click on **Documents** in the sidebar.
2. To upload a document, drag and drop a `.pdf`, `.md`, or `.txt` file onto the dropzone or click **Select File**.
3. Upload progress and indexing status are displayed in real time.
4. To remove an obsolete document, click **Remove** next to that document. Its retrievable content will be purged immediately from search.

---

## 6. System Diagnostics & Evaluation

- Visit the **Evaluation** tab to run the benchmark suite and inspect accuracy scores.
- Visit **System & Health** to view the active embedding model, vector store collection, and external storage paths.
