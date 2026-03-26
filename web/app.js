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
const lensTemplate = document.getElementById("lens-template");
const breakdownTemplate = document.getElementById("breakdown-item-template");
const signalTemplate = document.getElementById("signal-template");
const issueTemplate = document.getElementById("issue-template");

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

const postureMap = {
  "This page is structurally strong enough to be read, cited, and reused.": "這個頁面的結構已經足夠成熟，能被 AI 讀懂、引用與再利用。",
  "This page has a solid base, but a few missing signals are holding it back.": "這個頁面基礎不差，但還有幾個缺口拖住了整體表現。",
  "This page is understandable, but not consistently machine-ready.": "這個頁面大致看得懂，但還沒有穩定達到機器友善狀態。",
  "This page has content, but its answer structure is still weak.": "這個頁面有內容，但答案結構仍然偏弱。",
  "This page is not yet shaped like a reusable answer.": "這個頁面還沒有長成可被重複利用的答案形態。",
};

const severityMap = {
  critical: "關鍵",
  high: "高",
  medium: "中",
  low: "低",
};

const textMap = {
  "Title gives a usable discovery signal.": "標題已具備可用的發現訊號。",
  "Title exists but is not yet ideal for discovery.": "標題已存在，但對發現與搜尋仍不夠理想。",
  "Missing title.": "缺少標題。",
  "Meta description supports clean snippet generation.": "Meta description 有助於產生清楚的摘要片段。",
  "Meta description exists but can be sharper.": "Meta description 已存在，但還可以更精準。",
  "Missing meta description.": "缺少 meta description。",
  "Canonical is present.": "已有 canonical。",
  "Missing canonical.": "缺少 canonical。",
  "HTML lang is present.": "已有 HTML lang。",
  "Missing HTML lang.": "缺少 HTML lang。",
  "Fetch status is index-friendly.": "抓取狀態對索引友善。",
  "Fetch status may block normal discovery.": "抓取狀態可能會阻礙正常發現。",
  "No noindex directive detected.": "未偵測到 noindex 指令。",
  "Page appears to be noindex.": "頁面看起來帶有 noindex。",
  "Open Graph summary fields exist.": "已有 Open Graph 摘要欄位。",
  "Open Graph is partial.": "Open Graph 設定不完整。",
  "Missing Open Graph summary fields.": "缺少 Open Graph 摘要欄位。",
  "llms.txt exists, but this is only a minor discovery signal.": "已有 llms.txt，但這只是次要的發現訊號。",
  "llms.txt is absent, but this is not a core blocker.": "缺少 llms.txt，但這不是核心阻礙。",
  "JSON-LD was found.": "已偵測到 JSON-LD。",
  "No JSON-LD found.": "未偵測到 JSON-LD。",
  "Schema includes author, publisher, or date details.": "Schema 內含作者、發布者或日期資訊。",
  "Schema lacks author, publisher, and date detail.": "Schema 缺少作者、發布者與日期細節。",
  "Page has an H1.": "頁面有 H1。",
  "Missing H1.": "缺少 H1。",
  "H2 structure is clear.": "H2 結構清楚。",
  "Basic H2 structure exists.": "已有基本 H2 結構。",
  "Weak H2 structure.": "H2 結構偏弱。",
  "Secondary structure is strong.": "次層結構完整。",
  "Some secondary structure exists.": "已有部分次層結構。",
  "Weak secondary structure.": "次層結構偏弱。",
  "Internal linking supports machine understanding.": "內部連結有助於機器理解。",
  "Some internal linking exists.": "已有部分內部連結。",
  "No internal links found.": "未偵測到內部連結。",
  "Image alt signals exist.": "已有圖片 alt 訊號。",
  "Some image alt signals exist.": "已有部分圖片 alt 訊號。",
  "No image alt signals found.": "未偵測到圖片 alt 訊號。",
  "Opening paragraph is answer-snippet friendly.": "開頭段落適合被擷取成答案摘要。",
  "Opening paragraph exists but is not strongly answer-first.": "開頭段落已存在，但還不夠 answer-first。",
  "Missing a clear body opening paragraph.": "缺少清楚的正文開場段落。",
  "Page has FAQ or question-driven headings.": "頁面含 FAQ 或問題導向標題。",
  "Page has at least one question-driven heading.": "頁面至少有一個問題導向標題。",
  "Missing FAQ or question-driven sections.": "缺少 FAQ 或問題導向區塊。",
  "Bulleted content exists and is extractable.": "已有可抽取的條列內容。",
  "Some list content exists.": "已有部分列表內容。",
  "Missing list-style content.": "缺少列表型內容。",
  "Table content exists.": "已有表格內容。",
  "No table content found.": "未偵測到表格內容。",
  "Paragraph density is reasonable.": "段落密度合理。",
  "Paragraphs are likely too short or too long.": "段落可能過短或過長。",
  "Little to no paragraph content found.": "幾乎沒有正文段落內容。",
  "The page has enough heading chunks to be reusable.": "頁面有足夠的小標分塊，利於重用。",
  "The page has some heading chunking.": "頁面已有部分小標分塊。",
  "The page lacks reusable heading chunks.": "頁面缺少可重用的小標分塊。",
  "Author signal exists.": "已有作者訊號。",
  "Missing author signal.": "缺少作者訊號。",
  "Publish or update date exists.": "已有發布或更新日期。",
  "Missing freshness signal.": "缺少新鮮度訊號。",
  "Page cites multiple external domains.": "頁面引用了多個外部網域。",
  "Page cites at least one external domain.": "頁面至少引用了一個外部網域。",
  "Missing external citation signals.": "缺少外部引用訊號。",
  "Publisher or organization signal exists.": "已有發布者或組織訊號。",
  "Missing publisher or organization signal.": "缺少發布者或組織訊號。",
  "Content depth is substantial.": "內容深度充足。",
  "Content depth is moderate.": "內容深度中等。",
  "Content depth is thin.": "內容深度偏薄。",
  "High-risk topic detected; the trust bar is higher.": "偵測到高風險主題，信任門檻會更高。",
  "Medium-risk topic detected; trust signals still matter.": "偵測到中風險主題，信任訊號仍然重要。",
  "The page uses concrete details, numbers, or constraints.": "頁面使用了具體細節、數字或限制條件。",
  "The page includes some specific detail.": "頁面含有一些具體細節。",
  "The page lacks enough concrete specifics.": "頁面缺少足夠具體的細節。",
  "The page explains trade-offs instead of listing features only.": "頁面有說明取捨，而不是只列功能。",
  "The page does not surface clear trade-offs.": "頁面沒有清楚呈現取捨。",
  "The page synthesizes information into reusable structures.": "頁面已把資訊整理成可重用的結構。",
  "The page does not yet synthesize information into comparison structures.": "頁面還沒有把資訊整理成比較結構。",
  "The page combines depth with some evidence.": "頁面兼具一定深度與部分證據。",
  "The page has moderate detail.": "頁面具有中等程度的細節。",
  "The page still feels thin on original or synthesized detail.": "頁面在原創或整合細節上仍偏薄。",
  "Visible freshness helps the page carry current value.": "可見的新鮮度訊號有助於提升當前價值。",
  "The page surfaces a conclusion early.": "頁面在前段就提出結論。",
  "The page does not state the answer early enough.": "頁面太晚才講到答案。",
  "The page makes a recommendation, not just an observation.": "頁面有明確推薦，而不只是描述。",
  "The page does not clearly recommend or choose.": "頁面沒有清楚推薦或做出選擇。",
  "The page differentiates by audience or use case.": "頁面有依受眾或情境做區分。",
  "The page does not split the answer by scenario or persona.": "頁面沒有依情境或人物角色拆分答案。",
  "The page clarifies trade-offs.": "頁面有清楚說明取捨。",
  "The page does not make trade-offs explicit.": "頁面沒有把取捨講清楚。",
  "The page gives an actionable next step.": "頁面提供了可執行的下一步。",
  "The page does not guide the next action clearly.": "頁面沒有清楚指引下一步。",
  "Metadata is helping the page surface cleanly across search and social contexts.": "這個頁面的 metadata 有助於它在搜尋與社群場景中更清楚地被呈現。",
  "The page has some visibility signals, but metadata is incomplete.": "這個頁面已有部分可見性訊號，但 metadata 還不完整。",
  "The page lacks the baseline metadata needed for broader visibility.": "這個頁面缺少更廣泛可見性所需的基礎 metadata。",
  "The page uses concrete specifics and trade-offs, which feels more like added value.": "這個頁面有具體細節與取捨說明，因此更像真正有附加價值的內容。",
  "The page includes some concrete detail, but the synthesis layer can be stronger.": "這個頁面已有一些具體細節，但整合與提煉層還可以更強。",
  "The page still reads more like generic information than a value-added answer.": "這個頁面讀起來仍比較像一般資訊整理，而不是有附加價值的答案。",
  "Trust signals are weak. Add authorship, freshness, and verifiable references.": "信任訊號偏弱，建議補上作者、新鮮度與可驗證引用。",
  "Missing title": "缺少標題",
  "Title too short": "標題太短",
  "Title too long": "標題太長",
  "Missing meta description": "缺少 meta description",
  "Meta description too short": "Meta description 太短",
  "Meta description too long": "Meta description 太長",
  "Missing canonical": "缺少 canonical",
  "Missing HTML lang": "缺少 HTML lang",
  "Page marked noindex": "頁面被標記為 noindex",
  "Missing Open Graph title": "缺少 Open Graph title",
  "Missing Open Graph description": "缺少 Open Graph description",
  "Open Graph not configured": "Open Graph 未完整設定",
  "Missing JSON-LD": "缺少 JSON-LD",
  "No relevant schema type": "缺少合適的 schema 類型",
  "Schema missing author": "Schema 缺少作者",
  "Schema missing publisher": "Schema 缺少發布者",
  "Schema missing date": "Schema 缺少日期",
  "Missing FAQ or QA schema": "缺少 FAQ 或 QA schema",
  "Missing breadcrumb schema": "缺少 breadcrumb schema",
  "Missing page-level schema": "缺少頁面層級 schema",
  "Missing H2 sections": "缺少 H2 區塊",
  "Missing H3 depth": "缺少 H3 深度",
  "No question-style headings": "缺少問題式標題",
  "Missing FAQ section": "缺少 FAQ 區塊",
  "Missing list structure": "缺少列表結構",
  "List structure is thin": "列表結構偏薄",
  "Missing comparison table": "缺少比較表格",
  "Missing clear opening paragraph": "缺少清楚的開場段落",
  "Too few body paragraphs": "正文段落太少",
  "Content depth is not substantial": "內容深度仍不夠扎實",
  "Missing publish or update date": "缺少發布或更新日期",
  "Missing publisher signal": "缺少發布者訊號",
  "Missing external citations": "缺少外部引用",
  "Low citation diversity": "引用來源多樣性不足",
  "Missing internal links": "缺少內部連結",
  "Internal linking is thin": "內部連結偏少",
  "Missing image alt text": "缺少圖片 alt 文字",
  "Image alt coverage is low": "圖片 alt 覆蓋不足",
  "Secondary structure is weak": "次層結構偏弱",
  "Missing extractable answer units": "缺少可抽取的答案單位",
  "Missing llms.txt": "缺少 llms.txt",
  "Weak AI question-answer signal": "AI 問答訊號偏弱",
  "Weak decision-support structure": "決策支撐結構偏弱",
  "Answer is not stated early": "答案沒有提早說清楚",
  "No clear recommendation": "缺少明確推薦",
  "No scenario split": "缺少情境分流",
  "Trade-offs are not explicit": "缺少取捨說明",
  "No next action": "缺少下一步行動",
  "Low specificity": "具體性不足",
  "Specificity could be stronger": "具體性還可以更強",
  "High-risk topic with weak trust stack": "高風險主題但信任層不足",
  "Trust stack is thin": "信任層偏薄",
  "Metadata stack is thin": "Metadata 層偏薄",
  "The page does not expose a title.": "頁面沒有提供標題。",
  "Short titles are less descriptive in search and AI surfaces.": "過短標題在搜尋與 AI 場景中的描述力不足。",
  "Long titles are harder to surface cleanly.": "過長標題不利於乾淨呈現。",
  "The page is missing a summary snippet.": "頁面缺少摘要片段。",
  "Short descriptions often undersell the page.": "過短描述容易低估頁面價值。",
  "Long descriptions lose clarity.": "過長描述會降低清晰度。",
  "Canonical signals are missing.": "缺少 canonical 訊號。",
  "Language metadata is missing.": "缺少語言 metadata。",
  "The page appears blocked from indexability.": "頁面看起來被阻擋索引。",
  "The page lacks an OG title.": "頁面缺少 OG title。",
  "The page lacks an OG description.": "頁面缺少 OG description。",
  "The page has no complete Open Graph summary layer.": "頁面缺少完整的 Open Graph 摘要層。",
  "Structured data is absent.": "頁面沒有結構化資料。",
  "No useful schema type was detected.": "沒有偵測到有用的 schema 類型。",
  "The schema layer does not name an author.": "Schema 層沒有標出作者。",
  "The schema layer does not name a publisher.": "Schema 層沒有標出發布者。",
  "Structured data has no freshness field.": "結構化資料缺少新鮮度欄位。",
  "No FAQPage or QAPage schema was found.": "未偵測到 FAQPage 或 QAPage schema。",
  "Breadcrumb schema was not detected.": "未偵測到 breadcrumb schema。",
  "No WebPage or Article-like schema is present.": "缺少 WebPage 或 Article 類頁面 schema。",
  "The page lacks a primary heading.": "頁面缺少主要標題。",
  "The page lacks section anchors.": "頁面缺少段落錨點。",
  "The page has limited secondary structure.": "頁面的次層結構有限。",
  "The page is not framed around extractable questions.": "頁面沒有用可抽取的問題形式來組織。",
  "The page has no FAQ section.": "頁面沒有 FAQ 區塊。",
  "The page lacks bullet-style answer chunks.": "頁面缺少條列式答案區塊。",
  "The page has only a small amount of list structure.": "頁面只有少量列表結構。",
  "No table was found for structured comparison.": "頁面沒有用於結構化比較的表格。",
  "The page lacks a strong opening answer block.": "頁面缺少強而有力的開場答案區塊。",
  "The page has thin paragraph structure.": "頁面的段落結構偏薄。",
  "The page may not have enough depth to support citation or decision-making.": "頁面可能沒有足夠深度支撐引用或決策。",
  "The page may still feel lightweight for high-intent topics.": "對高意圖主題來說，頁面仍然偏輕。",
  "No author signal was detected.": "未偵測到作者訊號。",
  "Freshness is not visible.": "頁面沒有可見的新鮮度訊號。",
  "The publishing entity is unclear.": "發布實體不夠清楚。",
  "The page does not point to supporting outside sources.": "頁面沒有指向外部支撐來源。",
  "The page cites only one external domain.": "頁面只引用了一個外部網域。",
  "The page has no internal pathways to related content.": "頁面缺少通往相關內容的內部路徑。",
  "The page has only a small amount of internal linking.": "頁面只有少量內部連結。",
  "No image alt signals were found.": "未偵測到圖片 alt 訊號。",
  "Only a small amount of image alt text was found.": "只有少量圖片 alt 文字。",
  "The page lacks multi-level sectioning.": "頁面缺少多層次分段結構。",
  "The page is not broken into reusable answer chunks.": "頁面沒有被拆成可重用的答案單位。",
  "No llms.txt file was detected.": "未偵測到 llms.txt。",
  "The page lacks explicit QA framing.": "頁面缺少明確的問答框架。",
  "The page may be informative but not strongly decision-ready.": "頁面可能有資訊，但決策準備度不足。",
  "The page does not state its conclusion in the opening blocks.": "頁面沒有在前段講清楚結論。",
  "The page describes the topic but does not clearly choose or recommend.": "頁面有描述主題，但沒有清楚做出選擇或推薦。",
  "The page does not adapt the answer by audience, use case, or budget.": "頁面沒有依受眾、情境或預算調整答案。",
  "The page does not explain what the reader gains or gives up.": "頁面沒有說清楚讀者得到什麼或失去什麼。",
  "The page does not tell the reader what to do next.": "頁面沒有告訴讀者下一步要做什麼。",
  "The page lacks enough concrete detail to feel genuinely useful.": "頁面缺少足夠具體的細節，實用感不足。",
  "The page has some specifics, but not enough to feel differentiated.": "頁面有一些具體細節，但還不夠有辨識度。",
  "This looks like a high-risk topic, but trust signals are incomplete.": "這看起來是高風險主題，但信任訊號仍不完整。",
  "Too many trust signals are missing at once.": "同時缺少太多信任訊號。",
  "The page is missing too many metadata layers at once.": "頁面同時缺少太多 metadata 層。",
  "Add a clear title tag.": "加上清楚的 title tag。",
  "Expand the title to describe the page outcome.": "把標題寫得更完整，描述頁面要解決的結果。",
  "Trim the title to a tighter outcome-led version.": "把標題收斂成更聚焦結果導向的版本。",
  "Write a concise summary-oriented meta description.": "寫一段精簡且摘要導向的 meta description。",
  "Expand the description to summarize the page answer.": "把描述補得更完整，清楚總結頁面答案。",
  "Trim the description to the most useful promise.": "把描述收斂到最有價值的承諾。",
  "Add a canonical URL.": "加上 canonical URL。",
  "Add the correct lang attribute on the html tag.": "在 html 標籤上加上正確的 lang 屬性。",
  "Remove noindex if the page should be discoverable.": "如果這頁需要被發現，請移除 noindex。",
  "Add og:title metadata.": "加上 og:title metadata。",
  "Add og:description metadata.": "加上 og:description metadata。",
  "Add both og:title and og:description.": "同時補上 og:title 和 og:description。",
  "Add JSON-LD using a relevant schema type.": "使用合適的 schema 類型補上 JSON-LD。",
  "Add WebPage, Article, Product, FAQPage, or another relevant type.": "補上 WebPage、Article、Product、FAQPage 或其他合適的 schema 類型。",
  "Add author to structured data where relevant.": "在適合的 schema 中補上作者。",
  "Add publisher to structured data.": "在結構化資料中補上發布者。",
  "Add datePublished or dateModified.": "補上 datePublished 或 dateModified。",
  "Use FAQPage or QAPage where the content fits.": "若內容適合，請使用 FAQPage 或 QAPage。",
  "Add breadcrumb schema if the page sits in a content hierarchy.": "若頁面位於內容層級中，請補上 breadcrumb schema。",
  "Add a page-level schema type to frame the document.": "加上頁面層級 schema 來描述整份內容。",
  "Add one clear H1 that matches the page intent.": "加上一個和頁面意圖一致的 H1。",
  "Add H2 sections for the main ideas or decision criteria.": "為主要概念或決策標準補上 H2 區塊。",
  "Add H3 headings where subtopics need chunking.": "在子題需要分塊時補上 H3。",
  "Add question-style subheads or FAQ blocks when the page format supports it.": "若頁面型態適合，補上問題式小標或 FAQ 區塊。",
  "Add an FAQ section when the page benefits from objection handling or repeated questions.": "若頁面需要處理常見疑問，請補上 FAQ 區塊。",
  "Turn key comparison or takeaway sections into lists.": "把關鍵比較或重點段落改成列表。",
  "Expand comparison or takeaway lists.": "把比較或重點列表補得更完整。",
  "Add a table when the page compares options or specs.": "若頁面在比較選項或規格，請加上表格。",
  "Add a top paragraph that states the answer or recommendation.": "在頁首加上一段直接講答案或推薦的開場。",
  "Add more explanatory paragraphs around key decisions.": "圍繞關鍵決策補上更多說明段落。",
  "Add more original analysis, comparisons, and supporting detail.": "補上更多原創分析、比較與支撐細節。",
  "Add deeper sections for edge cases, trade-offs, or FAQs.": "補上更多邊界情境、取捨或 FAQ 區塊。",
  "Add author attribution in page copy or schema.": "在頁面內容或 schema 中補上作者標示。",
  "Add published and updated dates.": "補上發布日期與更新日期。",
  "Add brand or publisher information in copy or schema.": "在內容或 schema 中補上品牌或發布者資訊。",
  "Add references or source links for key claims.": "為關鍵主張補上參考資料或來源連結。",
  "Add a wider base of references if claims depend on trust.": "若主張依賴信任，請增加引用來源的多樣性。",
  "Add internal links to related workflows, guides, or product pages.": "補上指向相關流程、指南或產品頁的內部連結。",
  "Add more internal links to deepen the information architecture.": "補上更多內部連結，強化資訊架構。",
  "Add meaningful alt text to informative images.": "為資訊型圖片補上有意義的 alt 文字。",
  "Expand alt coverage on important images or diagrams.": "擴大重要圖片或圖表的 alt 覆蓋。",
  "Use H2 and H3 headings to separate major and minor ideas.": "用 H2 與 H3 把主次概念分開。",
  "Add lists, FAQs, or comparison blocks.": "補上列表、FAQ 或比較區塊。",
  "Consider publishing llms.txt at the site root.": "可考慮在網站根目錄提供 llms.txt。",
  "Add FAQ or question-led sections if the topic naturally has repeated questions.": "若主題本來就有常見問題，請補上 FAQ 或問題導向區塊。",
  "Add comparisons, criteria, and a recommendation path.": "補上比較、判準與推薦路徑。",
  "Put the recommendation or decision in the first 1 to 2 paragraphs.": "把推薦或結論放進前 1 到 2 段。",
  "Add a recommendation, ranking, or pick-by-scenario conclusion.": "補上推薦、排名或按情境選擇的結論。",
  "Split the answer by use case, budget, or user type.": "依使用情境、預算或用戶類型拆分答案。",
  "Add pros, cons, and trade-off framing.": "補上優點、缺點與取捨框架。",
  "Add a direct next step or choice path.": "補上一個直接的下一步或選擇路徑。",
  "Add prices, limits, dates, specs, or other concrete constraints.": "補上價格、限制、日期、規格或其他具體條件。",
  "Add more concrete numbers and constraints.": "補上更多具體數字與限制。",
  "For high-risk topics, add author, date, publisher, and citations together.": "對高風險主題，請一起補上作者、日期、發布者與引用。",
  "Add author, date, publisher, and references as a stack.": "把作者、日期、發布者與引用當作一整層一起補齊。",
  "Complete title, meta description, canonical, and OG coverage.": "把 title、meta description、canonical 與 OG 一起補齊。",
};

function yesNo(value) {
  return value ? "是" : "否";
}

function translateTopicRisk(value) {
  if (value === "high") return "高";
  if (value === "medium") return "中";
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

function translateText(value) {
  return textMap[value] || value;
}

function translateDynamicText(value) {
  if (value.startsWith("Detected schema types: ")) {
    return value.replace("Detected schema types: ", "偵測到的 schema 類型：");
  }

  if (value.startsWith("Good extraction shape with ")) {
    const partMap = {
      "schema exists": "schema",
      "FAQ exists": "FAQ",
      "list structure exists": "列表結構",
    };
    const raw = value.replace("Good extraction shape with ", "").replace(".", "");
    const translated = raw
      .split(",")
      .map((part) => part.trim())
      .map((part) => partMap[part] || part);
    return `可抽取性基礎不錯，目前已具備 ${translated.join("、")}。`;
  }

  if (value.startsWith("Trust layer includes ")) {
    const partMap = {
      author: "作者",
      date: "日期",
      publisher: "發布者",
      citations: "引用",
    };
    const hasRiskSuffix = value.endsWith(" High-risk topic detected.");
    const raw = value.replace("Trust layer includes ", "").replace(" High-risk topic detected.", "").replace(".", "");
    const translated = raw
      .split(",")
      .map((part) => part.trim())
      .map((part) => partMap[part] || part);
    return `信任層目前包含 ${translated.join("、")}。${hasRiskSuffix ? " 另外，這是高風險主題，信任要求更高。" : ""}`;
  }

  return translateText(value);
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
  if (score >= 8.5) return "strong";
  if (score >= 6.5) return "steady";
  if (score >= 4.5) return "fragile";
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
    node.querySelector(".lens-summary").textContent = translateDynamicText(lens.summary);
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
    node.querySelector(".breakdown-reason").textContent = translateDynamicText(item.reasons[0] || "目前沒有額外說明。");
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
    node.querySelector(".issue-title").textContent = translateText(issue.title);
    node.querySelector(".issue-description").textContent = `問題說明：${translateText(issue.description)}`;
    node.querySelector(".issue-fix").textContent = `建議修正：${translateText(issue.fix)}`;
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

function classifyScore(score) {
  if (score >= 8.5) return "高完成度的 AI 可見性資產";
  if (score >= 7.0) return "基礎很強，但仍有可補的缺口";
  if (score >= 5.0) return "可讀，但還沒有完全 answer-ready";
  if (score >= 3.0) return "有資訊，但結構偏弱";
  return "AI 答案可見性準備度偏低";
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
  }
});
