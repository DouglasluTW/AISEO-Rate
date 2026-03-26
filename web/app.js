const form = document.getElementById("score-form");
const urlInput = document.getElementById("url-input");
const submitButton = document.getElementById("submit-button");
const statusText = document.getElementById("status-text");
const scoreValue = document.getElementById("score-value");
const scoreRing = document.getElementById("score-ring");
const scoreHeadline = document.getElementById("score-headline");
const sourceLine = document.getElementById("source-line");
const postureLine = document.getElementById("posture-line");
const checksRun = document.getElementById("checks-run");
const issuesFound = document.getElementById("issues-found");
const warningBox = document.getElementById("warning-box");
const lensGrid = document.getElementById("lens-grid");
const breakdownList = document.getElementById("breakdown-list");
const issueList = document.getElementById("issue-list");
const signalsGrid = document.getElementById("signals-grid");
const statsStatus = document.getElementById("stats-status");
const visitCount = document.getElementById("visit-count");
const scoreCount = document.getElementById("score-count");
const successCount = document.getElementById("success-count");
const failureCount = document.getElementById("failure-count");
const domainWindow = document.getElementById("domain-window");
const domainList = document.getElementById("domain-list");
const lensTemplate = document.getElementById("lens-template");
const breakdownTemplate = document.getElementById("breakdown-item-template");
const signalTemplate = document.getElementById("signal-template");
const issueTemplate = document.getElementById("issue-template");
const domainTemplate = document.getElementById("domain-template");

const signalOrder = [
  ["標題", (payload) => payload.signals.title || "未偵測"],
  ["Meta description", (payload) => (payload.signals.meta_description ? "已偵測" : "缺少")],
  ["Canonical", (payload) => (payload.signals.canonical ? "已偵測" : "缺少")],
  ["Schema 類型", (payload) => (payload.signals.schema_types.length ? payload.signals.schema_types.join(", ") : "無")],
  ["主題風險", (payload) => translateTopicRisk(payload.signals.topic_risk)],
  ["FAQ 區塊", (payload) => yesNo(payload.signals.has_faq_section)],
  ["是否先給結論", (payload) => yesNo(payload.signals.conclusion_first)],
  ["是否有明確推薦", (payload) => yesNo(payload.signals.recommendation_signal)],
  ["是否有取捨說明", (payload) => yesNo(payload.signals.tradeoff_signal)],
  ["內部連結數", (payload) => String(payload.signals.internal_links)],
  ["外部連結數", (payload) => String(payload.signals.external_links)],
  ["字數", (payload) => String(payload.signals.word_count)],
  ["具體細節數", (payload) => String(payload.signals.specificity_markers)],
  ["圖片 alt 數", (payload) => String(payload.signals.image_alts)],
  ["llms.txt", (payload) => (payload.signals.llms_txt_found ? "已偵測" : "未偵測")],
];

const lensNameMap = {
  Extractability: "可抽取性",
  Resolution: "解題能力",
  "Citation trust": "引用信任",
  "Surface visibility": "表面可見性",
  "Added value": "附加價值",
};

const breakdownNameMap = {
  "Discovery and indexability": "發現與索引能力",
  "Machine readability": "機器可讀性",
  "Answer extractability": "答案可抽取性",
  "Trust and citation": "信任與引用",
  "Added value": "附加價值",
  "Task resolution": "任務解決度",
};

const severityMap = {
  critical: "關鍵",
  high: "高",
  medium: "中",
  low: "低",
};

const postureMap = {
  "This page is structurally strong enough to be read, cited, and reused.": "這個頁面的結構已經足夠成熟，能被 AI 讀懂、引用與再利用。",
  "This page has a solid base, but a few missing signals are holding it back.": "這個頁面基礎不差，但還有幾個缺口拖住了整體表現。",
  "This page is understandable, but not consistently machine-ready.": "這個頁面大致看得懂，但還沒有穩定達到機器友善的狀態。",
  "This page has content, but its answer structure is still weak.": "這個頁面有內容，但答案結構仍然偏弱。",
  "This page is not yet shaped like a reusable answer.": "這個頁面還沒有長成可被重複利用的答案形態。",
};

function yesNo(value) {
  return value ? "是" : "否";
}

function translateTopicRisk(value) {
  if (value === "high") {
    return "高";
  }
  if (value === "medium") {
    return "中";
  }
  return "低";
}

function translateLensName(name) {
  return lensNameMap[name] || name;
}

function translateBreakdownName(name) {
  return breakdownNameMap[name] || name;
}

function translateSeverity(value) {
  return severityMap[value] || value;
}

function translatePosture(value) {
  return postureMap[value] || value;
}

function setLoading(isLoading) {
  submitButton.disabled = isLoading;
  statusText.textContent = isLoading ? "分析中" : "待命中";
}

function setScore(score) {
  const safeScore = Number.isFinite(score) ? score : 0;
  scoreValue.textContent = Number.isFinite(score) ? safeScore.toFixed(1) : "--";
  const degrees = `${(Math.max(0, Math.min(safeScore, 10)) / 10) * 360}deg`;
  scoreRing.style.setProperty("--ring-angle", degrees);
}

function lensTone(score) {
  if (score >= 8.5) {
    return "strong";
  }
  if (score >= 6.5) {
    return "steady";
  }
  if (score >= 4.5) {
    return "fragile";
  }
  return "weak";
}

function renderLenses(payload) {
  lensGrid.replaceChildren();
  payload.lenses.forEach((lens) => {
    const node = lensTemplate.content.cloneNode(true);
    const root = node.querySelector(".lens-card");
    root.dataset.tone = lensTone(lens.score);
    node.querySelector(".lens-name").textContent = translateLensName(lens.name);
    node.querySelector(".lens-score").textContent = `${lens.score.toFixed(1)} / 10`;
    node.querySelector(".lens-summary").textContent = lens.summary;
    lensGrid.appendChild(node);
  });
}

function renderBreakdown(payload) {
  breakdownList.replaceChildren();
  payload.breakdown.forEach((item) => {
    const node = breakdownTemplate.content.cloneNode(true);
    node.querySelector("h3").textContent = translateBreakdownName(item.name);
    node.querySelector(".breakdown-score").textContent = `${item.points.toFixed(1)} / ${item.max_points.toFixed(1)}`;
    node.querySelector(".meter-fill").style.width = `${(item.points / item.max_points) * 100}%`;
    node.querySelector(".breakdown-reason").textContent = item.reasons[0] || "目前沒有額外說明。";
    breakdownList.appendChild(node);
  });
}

function renderIssues(payload) {
  issueList.replaceChildren();
  checksRun.textContent = String(payload.audit.checks_run);
  issuesFound.textContent = String(payload.audit.issues_found);

  if (!payload.audit.issues.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "目前沒有偵測到優先修正問題。";
    issueList.appendChild(empty);
    return;
  }

  payload.audit.issues.slice(0, 6).forEach((issue) => {
    const node = issueTemplate.content.cloneNode(true);
    node.querySelector(".issue-severity").textContent = translateSeverity(issue.severity);
    node.querySelector(".issue-title").textContent = issue.title;
    node.querySelector(".issue-description").textContent = `問題說明：${issue.description}`;
    node.querySelector(".issue-fix").textContent = `建議修正：${issue.fix}`;
    issueList.appendChild(node);
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
  postureLine.textContent = translatePosture(payload.posture);

  const warnings = [];
  if (payload.fetch_warning) {
    warnings.push(payload.fetch_warning);
  }
  if (payload.looks_like_block_page) {
    warnings.push("抓到的內容看起來像驗證頁、封鎖頁或存取限制頁。");
  }

  if (warnings.length) {
    warningBox.textContent = warnings.join(" ");
    warningBox.classList.remove("hidden");
  } else {
    warningBox.textContent = "";
    warningBox.classList.add("hidden");
  }

  renderLenses(payload);
  renderBreakdown(payload);
  renderIssues(payload);
  renderSignals(payload);
}

function classifyScore(score) {
  if (score >= 8.5) {
    return "高完成度的 AI 可見性資產";
  }
  if (score >= 7.0) {
    return "基礎很強，但仍有可補的缺口";
  }
  if (score >= 5.0) {
    return "可讀，但還沒有完全 answer-ready";
  }
  if (score >= 3.0) {
    return "有資訊，但結構偏弱";
  }
  return "AI 答案可見性準備度偏低";
}

function renderError(message) {
  setScore(Number.NaN);
  scoreHeadline.textContent = "這個頁面目前無法分析";
  sourceLine.textContent = message;
  postureLine.textContent = "請求在可靠分數產生前就失敗了，因此這次沒有形成可信的 AI SEO 狀態判讀。";
  checksRun.textContent = "--";
  issuesFound.textContent = "--";
  warningBox.classList.add("hidden");
  lensGrid.replaceChildren();
  breakdownList.replaceChildren();
  issueList.replaceChildren();
  signalsGrid.replaceChildren();
}

function renderStats(payload) {
  visitCount.textContent = String(payload.total_visits);
  scoreCount.textContent = String(payload.total_scores);
  successCount.textContent = String(payload.score_successes);
  failureCount.textContent = String(payload.score_failures);
  domainWindow.textContent = `最近 ${payload.recent_domain_window} 次提交`;
  domainList.replaceChildren();

  const maxCount = Math.max(...payload.recent_domains.map((item) => item.count), 1);
  if (!payload.recent_domains.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "目前還沒有最近的評分 domain。";
    domainList.appendChild(empty);
    return;
  }

  payload.recent_domains.forEach((item) => {
    const node = domainTemplate.content.cloneNode(true);
    node.querySelector(".domain-name").textContent = item.domain;
    node.querySelector(".domain-count").textContent = `${item.count} 次`;
    node.querySelector(".domain-bar-fill").style.width = `${(item.count / maxCount) * 100}%`;
    domainList.appendChild(node);
  });
}

async function fetchStats() {
  statsStatus.textContent = "讀取中";
  try {
    const response = await fetch("/api/stats");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Stats request failed");
    }
    renderStats(payload);
    statsStatus.textContent = "已更新";
  } catch (error) {
    statsStatus.textContent = "讀取失敗";
  }
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
    renderError(error.message || "發生未預期錯誤");
  } finally {
    setLoading(false);
    await fetchStats();
  }
});

fetchStats();
