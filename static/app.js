const uploadForm = document.getElementById("upload-form");
const fileA = document.getElementById("file-a");
const fileB = document.getElementById("file-b");
const runButton = document.getElementById("run-button");
const sampleButton = document.getElementById("sample-button");

const statusSection = document.getElementById("status-section");
const statusSteps = document.getElementById("status-steps");
const statusMessage = document.getElementById("status-message");

const resultsSection = document.getElementById("results-section");
const resultsSummary = document.getElementById("results-summary");
const resultsBody = document.getElementById("results-body");

const detailSection = document.getElementById("detail-section");
const detailContent = document.getElementById("detail-content");
const closeDetailButton = document.getElementById("close-detail");

let currentMatches = [];

sampleButton.addEventListener("click", async () => {
  const [productsBlob, productsV2Blob] = await Promise.all([
    fetch("/samples/products.csv").then((r) => r.blob()),
    fetch("/samples/products_v2.csv").then((r) => r.blob()),
  ]);

  const dt1 = new DataTransfer();
  dt1.items.add(new File([productsBlob], "products.csv", { type: "text/csv" }));
  fileA.files = dt1.files;

  const dt2 = new DataTransfer();
  dt2.items.add(new File([productsV2Blob], "products_v2.csv", { type: "text/csv" }));
  fileB.files = dt2.files;

  uploadForm.requestSubmit();
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!fileA.files[0] || !fileB.files[0]) return;

  runButton.disabled = true;
  sampleButton.disabled = true;
  resultsSection.classList.add("hidden");
  detailSection.classList.add("hidden");
  statusSection.classList.remove("hidden");
  resetSteps();
  statusMessage.textContent = "";
  statusMessage.classList.remove("error");

  try {
    await runPipeline(fileA.files[0], fileB.files[0]);
  } catch (err) {
    statusMessage.textContent = err.message;
    statusMessage.classList.add("error");
  } finally {
    runButton.disabled = false;
    sampleButton.disabled = false;
  }
});

function resetSteps() {
  for (const li of statusSteps.children) {
    li.classList.remove("active", "done", "failed");
  }
}

function markStep(stepName, state) {
  const li = statusSteps.querySelector(`[data-step="${stepName}"]`);
  if (!li) return;
  li.classList.remove("active", "done", "failed");
  li.classList.add(state);
}

async function uploadDataset(file, stepName) {
  markStep(stepName, "active");
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch("/datasets", { method: "POST", body: formData });
  const body = await response.json();

  if (!response.ok) {
    markStep(stepName, "failed");
    throw new Error(`Upload of ${file.name} failed: ${JSON.stringify(body)}`);
  }

  markStep(stepName, "done");
  return body.dataset_id;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: payload ? { "Content-Type": "application/json" } : undefined,
    body: payload ? JSON.stringify(payload) : undefined,
  });
  const body = await response.json();
  return { ok: response.ok, status: response.status, body };
}

async function runPipeline(fileObjA, fileObjB) {
  const datasetAId = await uploadDataset(fileObjA, "upload-a");
  const datasetBId = await uploadDataset(fileObjB, "upload-b");

  markStep("match", "active");
  const matchResult = await postJson("/match", {
    dataset_a_id: datasetAId,
    dataset_b_id: datasetBId,
  });

  if (!matchResult.ok) {
    markStep("match", "failed");
    const detail = matchResult.body.detail;
    if (detail && detail.compatibility_check) {
      statusMessage.textContent =
        `Datasets rejected as incompatible.\n\nReasoning: ${detail.compatibility_check.reasoning}`;
    } else {
      statusMessage.textContent = `POST /match failed: ${JSON.stringify(matchResult.body)}`;
      statusMessage.classList.add("error");
    }
    return;
  }
  markStep("match", "done");
  statusMessage.textContent = `Compatibility verdict: ${matchResult.body.compatibility_check.verdict}\n${matchResult.body.compatibility_check.reasoning}`;

  const matchJobId = matchResult.body.match_job_id;

  markStep("block", "active");
  const blockResult = await postJson(`/match-jobs/${matchJobId}/block`);
  if (!blockResult.ok) {
    markStep("block", "failed");
    throw new Error(`Blocking failed: ${JSON.stringify(blockResult.body)}`);
  }
  markStep("block", "done");

  markStep("score", "active");
  const scoreResult = await postJson(`/match-jobs/${matchJobId}/score`);
  if (!scoreResult.ok) {
    markStep("score", "failed");
    throw new Error(`Scoring failed: ${JSON.stringify(scoreResult.body)}`);
  }
  markStep("score", "done");

  markStep("judge", "active");
  statusMessage.textContent = "Running LLM judge on ambiguous pairs (this can take a minute)...";
  const judgeResult = await postJson(`/match-jobs/${matchJobId}/judge`);
  if (!judgeResult.ok) {
    markStep("judge", "failed");
    throw new Error(`Judging failed: ${JSON.stringify(judgeResult.body)}`);
  }
  markStep("judge", "done");

  markStep("finalize", "active");
  const finalizeResult = await postJson(`/match-jobs/${matchJobId}/finalize`);
  if (!finalizeResult.ok) {
    markStep("finalize", "failed");
    throw new Error(`Finalize failed: ${JSON.stringify(finalizeResult.body)}`);
  }
  markStep("finalize", "done");

  statusMessage.textContent = `Pipeline complete. Final status tally: ${JSON.stringify(finalizeResult.body.final_status_tally)}`;

  await loadResults(matchJobId);
}

async function loadResults(matchJobId) {
  const response = await fetch(`/matches/${matchJobId}`);
  const body = await response.json();
  currentMatches = body.matches;

  resultsSection.classList.remove("hidden");
  resultsSummary.textContent = `${body.count} candidate pair(s)`;
  resultsBody.innerHTML = "";

  const sorted = [...currentMatches].sort(
    (a, b) => (b.hybrid_score ?? 0) - (a.hybrid_score ?? 0)
  );

  for (const match of sorted) {
    const row = document.createElement("tr");
    row.dataset.matchId = match.match_id;

    const nameA = recordDisplayName(match.record_a);
    const nameB = recordDisplayName(match.record_b);
    const score = match.hybrid_score != null ? match.hybrid_score.toFixed(4) : "-";

    row.innerHTML = `
      <td>${escapeHtml(nameA)}</td>
      <td>${escapeHtml(nameB)}</td>
      <td>${score}</td>
      <td>${statusBadge(match.final_status)}</td>
    `;
    row.addEventListener("click", () => showDetail(match));
    resultsBody.appendChild(row);
  }
}

function recordDisplayName(record) {
  if (!record || !record.canonical_json) return "?";
  const c = record.canonical_json;
  return c.name || c.title || Object.values(c)[0] || "?";
}

function statusBadge(status) {
  if (!status) return "";
  const label = status.replace(/_/g, " ");
  return `<span class="badge badge-${status}">${escapeHtml(label)}</span>`;
}

function showDetail(match) {
  detailSection.classList.remove("hidden");
  detailSection.scrollIntoView({ behavior: "smooth", block: "nearest" });

  const recordA = match.record_a ? match.record_a.canonical_json : {};
  const recordB = match.record_b ? match.record_b.canonical_json : {};

  let html = `
    <div class="detail-records">
      <div class="detail-record">
        <h4>Record A</h4>
        <pre>${escapeHtml(JSON.stringify(recordA, null, 2))}</pre>
      </div>
      <div class="detail-record">
        <h4>Record B</h4>
        <pre>${escapeHtml(JSON.stringify(recordB, null, 2))}</pre>
      </div>
    </div>
  `;

  html += `<p><strong>Status:</strong> ${statusBadge(match.final_status)}</p>`;
  html += `<p><strong>Blocking score:</strong> ${match.blocking_score != null ? match.blocking_score.toFixed(4) : "-"} &nbsp; <strong>Hybrid score:</strong> ${match.hybrid_score != null ? match.hybrid_score.toFixed(4) : "-"}</p>`;

  if (match.llm_verdict) {
    html += `
      <div class="detail-reasoning">
        <strong>LLM verdict:</strong> match=${match.llm_verdict.match}, confidence=${escapeHtml(match.llm_verdict.confidence || "")}<br>
        ${escapeHtml(match.llm_verdict.reasoning || "")}
      </div>
    `;
  } else {
    html += `<p><em>Not sent to the LLM judge (resolved by hybrid scoring alone).</em></p>`;
  }

  if (match.conflicts && match.conflicts.length > 0) {
    html += `<table class="conflicts-table"><thead><tr><th>Field</th><th>Value A</th><th>Value B</th><th>Type</th></tr></thead><tbody>`;
    for (const c of match.conflicts) {
      html += `<tr>
        <td>${escapeHtml(c.field_name || "")}</td>
        <td>${escapeHtml(c.value_a || "")}</td>
        <td>${escapeHtml(c.value_b || "")}</td>
        <td class="conflict-type">${escapeHtml(c.conflict_type || "")}</td>
      </tr>`;
    }
    html += `</tbody></table>`;
  } else {
    html += `<p><em>No conflicts recorded.</em></p>`;
  }

  detailContent.innerHTML = html;
}

closeDetailButton.addEventListener("click", () => {
  detailSection.classList.add("hidden");
});

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = String(value ?? "");
  return div.innerHTML;
}
