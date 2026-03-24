const form = document.getElementById("score-form");
const urlInput = document.getElementById("url-input");
const submitButton = document.getElementById("submit-button");
const statusText = document.getElementById("status-text");
const scoreValue = document.getElementById("score-value");
const scoreRing = document.getElementById("score-ring");
const scoreHeadline = document.getElementById("score-headline");
const sourceLine = document.getElementById("source-line");
const warningBox = document.getElementById("warning-box");
const breakdownList = document.getElementById("breakdown-list");
const suggestionsList = document.getElementById("suggestions-list");
const signalsGrid = document.getElementById("signals-grid");
const breakdownTemplate = document.getElementById("breakdown-item-template");
const signalTemplate = document.getElementById("signal-template");

const signalOrder = [
  ["Title", (payload) => payload.signals.title || "Missing"],
  ["Meta description", (payload) => payload.signals.meta_description ? "Detected" : "Missing"],
  ["Canonical", (payload) => payload.signals.canonical ? "Detected" : "Missing"],
  ["Schema types", (payload) => payload.signals.schema_types.length ? payload.signals.schema_types.join(", ") : "None"],
  ["FAQ section", (payload) => payload.signals.has_faq_section ? "Yes" : "No"],
  ["Internal links", (payload) => String(payload.signals.internal_links)],
  ["External links", (payload) => String(payload.signals.external_links)],
  ["Word count", (payload) => String(payload.signals.word_count)],
  ["Image alts", (payload) => String(payload.signals.image_alts)],
  ["llms.txt", (payload) => payload.signals.llms_txt_found ? "Detected" : "Not detected"],
];

function setLoading(isLoading) {
  submitButton.disabled = isLoading;
  statusText.textContent = isLoading ? "Scoring..." : "Ready";
}

function setScore(score) {
  const safeScore = Number.isFinite(score) ? score : 0;
  scoreValue.textContent = Number.isFinite(score) ? safeScore.toFixed(1) : "--";
  const degrees = `${(Math.max(0, Math.min(safeScore, 10)) / 10) * 360}deg`;
  scoreRing.style.setProperty("--ring-angle", degrees);
}

function renderBreakdown(payload) {
  breakdownList.replaceChildren();
  payload.breakdown.forEach((item) => {
    const node = breakdownTemplate.content.cloneNode(true);
    node.querySelector("h3").textContent = item.name;
    node.querySelector(".breakdown-score").textContent = `${item.points.toFixed(1)} / ${item.max_points.toFixed(1)}`;
    node.querySelector(".meter-fill").style.width = `${(item.points / item.max_points) * 100}%`;
    node.querySelector(".breakdown-reason").textContent = item.reasons[0] || "No notes.";
    breakdownList.appendChild(node);
  });
}

function renderSuggestions(payload) {
  suggestionsList.replaceChildren();
  payload.suggestions.slice(0, 6).forEach((suggestion) => {
    const item = document.createElement("li");
    item.textContent = suggestion;
    suggestionsList.appendChild(item);
  });
}

function renderSignals(payload) {
  signalsGrid.replaceChildren();
  signalOrder.forEach(([label, getter]) => {
    const node = signalTemplate.content.cloneNode(true);
    node.querySelector(".signal-name").textContent = label;
    node.querySelector(".signal-value").textContent = getter(payload);
    signalsGrid.appendChild(node);
  });
}

function renderResult(payload) {
  setScore(payload.score);
  scoreHeadline.textContent = classifyScore(payload.score);
  sourceLine.textContent = payload.source;

  const warnings = [];
  if (payload.fetch_warning) {
    warnings.push(payload.fetch_warning);
  }
  if (payload.looks_like_block_page) {
    warnings.push("The fetched page looks like a challenge or access-denied response.");
  }

  if (warnings.length) {
    warningBox.textContent = warnings.join(" ");
    warningBox.classList.remove("hidden");
  } else {
    warningBox.textContent = "";
    warningBox.classList.add("hidden");
  }

  renderBreakdown(payload);
  renderSuggestions(payload);
  renderSignals(payload);
}

function classifyScore(score) {
  if (score >= 8.5) {
    return "Strong machine-readable page";
  }
  if (score >= 7.0) {
    return "Solid baseline with a few gaps";
  }
  if (score >= 5.0) {
    return "Usable, but not reliably extractable";
  }
  if (score >= 3.0) {
    return "Thin answer structure";
  }
  return "Weak AI SEO foundation";
}

function renderError(message) {
  setScore(Number.NaN);
  scoreHeadline.textContent = "Unable to score this page";
  sourceLine.textContent = message;
  warningBox.classList.add("hidden");
  breakdownList.replaceChildren();
  suggestionsList.replaceChildren();
  signalsGrid.replaceChildren();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = urlInput.value.trim();
  if (!url) {
    return;
  }

  setLoading(true);
  try {
    const response = await fetch("/api/score", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Request failed");
    }
    renderResult(payload);
  } catch (error) {
    renderError(error.message || "Unexpected error");
  } finally {
    setLoading(false);
  }
});
