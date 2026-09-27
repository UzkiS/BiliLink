// BiliLink 网页界面：识别输入、列出分 P、复制链接与预览播放。
// 生成的链接都指向本服务而不是 B 站 CDN：每次播放时由服务端重新解析，因此链接长期有效，
// 并且会为每位观看者选择其所在地区的 CDN 节点。链接相对于页面地址生成，
// 部署在根域名、子域名或反向代理的子路径下时，都与页面位于同一前缀之下。

// 与 bililink.bilibili.BVID_PATTERN 一致（由 tests/test_consistency.py 保证）。
const BVID_PATTERN = "BV[1-9A-HJ-NP-Za-km-z]{10}";
const BVID = new RegExp(BVID_PATTERN);
const PAGE_PARAM = /[?&]p=(\d+)/;
const LIVE_URL = /live\.bilibili\.com\/(?:h5\/)?(\d+)/;
const ROOM_ID = /^\d+$/;
const SHORT_LINK = /b23\.tv\//;
const PAGE_RANGE = /^p?(\d+)\s*[-~～]\s*p?(\d+)$/;
const HLS_MIME_TYPE = "application/vnd.apple.mpegurl";

const $ = (selector) => document.querySelector(selector);
const form = $("#lookup");
const query = $("#query");
const submitButton = $("#submit");
const result = $("#result");
const layout = $("#layout");
const resultTitle = $("#result-title");
const resultMeta = $("#result-meta");
const resultHint = $("#result-hint");
const stage = $("#stage");
const cover = $("#cover");
const player = $("#player");
const overlay = $("#overlay");
const playButton = $("#play");
const stopButton = $("#stop");
const stageCaption = $("#stage-caption");
const currentLabel = $("#current-label");
const currentUrl = $("#current-url");
const episodes = $("#episodes");
const episodeCount = $("#episode-count");
const filterInput = $("#filter");
const copyAllButton = $("#copy-all");
const pageList = $("#pages");
const pageTemplate = $("#page-template");
const linkPattern = $("#link-pattern");
const patternNote = $("#pattern-note");
const toast = $("#toast");

/** 本服务返回的错误（JSON 中的 error 字段），可直接展示给用户。 */
class ServiceError extends Error {}

// 每次查询或预览时递增，用来丢弃已被新操作取代的异步结果。
let lookupId = 0;
let previewId = 0;
let hls = null;
let toastTimer = 0;
/** 当前结果中的全部链接：{ label, title, duration, url, page, live, row }。 */
let entries = [];
/** 当前选中的链接在 entries 中的序号：视频下方显示它的链接，播放按钮预览它。 */
let current = 0;

form.addEventListener("submit", (event) => {
  event.preventDefault();
  lookup(query.value.trim());
});
// 粘贴后直接生成链接，省去再点一次按钮。
query.addEventListener("paste", () => setTimeout(() => form.requestSubmit()));
for (const chip of document.querySelectorAll("[data-example]")) {
  chip.addEventListener("click", () => {
    query.value = chip.dataset.example;
    form.requestSubmit();
  });
}
playButton.addEventListener("click", () => preview());
stopButton.addEventListener("click", stopPreview);
player.addEventListener("error", () => {
  if (!player.hidden) setStage("error", "播放失败：浏览器无法播放该媒体");
});
$("#copy-current").addEventListener("click", () => copy(entries[current].url, copiedMessage(current)));
copyAllButton.addEventListener("click", () => {
  const visible = entries.filter((entry) => !entry.row.hidden);
  copy(visible.map((entry) => entry.url).join("\n"), `已复制 ${visible.length} 条链接`);
});
filterInput.addEventListener("input", applyFilter);
// 点击分 P 即预览该分 P，行尾的按钮只复制链接。
pageList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const index = Number(button.closest("li").dataset.index);
  if (button.dataset.action === "copy") {
    copy(entries[index].url, copiedMessage(index));
  } else {
    select(index);
    preview();
  }
});

async function lookup(text) {
  const target = parseInput(text);
  if (target === null) {
    showToast(
      SHORT_LINK.test(text)
        ? "暂不支持 b23.tv 短链接：请在浏览器中打开它，再复制跳转后的网址"
        : "无法识别：请输入 BV 号、视频网址、直播间号或直播间网址",
      true,
    );
    return;
  }
  const id = ++lookupId;
  setBusy(true);
  try {
    const view = target.kind === "live" ? liveView(target) : await videoView(target);
    if (id !== lookupId) return;
    showResult(view);
    if (view.warning) showToast(view.warning, true);
  } catch (error) {
    if (id === lookupId) showToast(error.message, true);
  } finally {
    if (id === lookupId) setBusy(false);
  }
}

/** 从输入中识别视频（BV 号与可选的分 P）或直播间号，无法识别时返回 null。 */
function parseInput(text) {
  const bvid = BVID.exec(text)?.[0];
  if (bvid) {
    const page = PAGE_PARAM.exec(text)?.[1];
    return { kind: "video", bvid, page: page ? Number(page) : null };
  }
  const roomId = LIVE_URL.exec(text)?.[1] ?? (ROOM_ID.test(text) ? text : null);
  return roomId ? { kind: "live", roomId: Number(roomId) } : null;
}

function liveView({ roomId }) {
  return {
    title: `直播间 ${roomId}`,
    titleUrl: `https://live.bilibili.com/${roomId}`,
    meta: "HLS 直播流（m3u8）",
    hint: "链接长期有效：每次播放都会重新获取直播流。",
    cover: "",
    entries: [{ label: "直播", title: "", url: serviceUrl(`live/${roomId}`), live: true }],
    selected: 0,
  };
}

async function videoView({ bvid, page }) {
  const video = await fetchJson(`api/video/${bvid}`);
  const { pages } = video;
  const multiPage = pages.length > 1;
  const selected = pages.findIndex((item) => item.page === page);
  const duration = formatDuration(pages.reduce((total, item) => total + item.duration, 0));
  return {
    title: video.title,
    titleUrl: `https://www.bilibili.com/video/${bvid}`,
    meta: multiPage ? `${bvid} · 共 ${pages.length} P · 总时长 ${duration}` : `${bvid} · 时长 ${duration}`,
    hint: "链接长期有效：每次播放都会重新解析，并为观看者选择所在地区的 CDN 节点。",
    cover: video.cover,
    entries: pages.map((item) => ({
      label: `P${item.page}`,
      title: item.title,
      duration: item.duration,
      url: serviceUrl(multiPage ? `${bvid}?p=${item.page}` : bvid),
      page: item.page,
      live: false,
    })),
    pattern: serviceUrl(`${bvid}?p=`),
    selected: Math.max(selected, 0),
    warning: page !== null && selected < 0 ? `该视频没有第 ${page} P（共 ${pages.length} P）` : "",
  };
}

function showResult(view) {
  stopPreview();
  entries = view.entries;
  const multiple = entries.length > 1;
  resultTitle.textContent = view.title;
  resultTitle.title = view.title;
  resultTitle.href = view.titleUrl;
  resultMeta.textContent = view.meta;
  resultHint.textContent = view.hint;
  resultHint.title = view.hint;
  if (view.cover) {
    cover.src = view.cover;
  } else {
    cover.removeAttribute("src");
  }
  layout.classList.toggle("multi", multiple);
  episodes.hidden = !multiple;
  currentLabel.hidden = !multiple;
  patternNote.hidden = !multiple;
  if (multiple) renderEpisodes(view.pattern);
  document.body.classList.add("has-result");
  result.hidden = false;
  select(view.selected);
  // 宽屏时选集在侧栏内滚动：把选中的分 P 滚到列表中间（只滚动列表，页面不动）。
  const row = entries[current].row;
  if (row) pageList.scrollTop = row.offsetTop - (pageList.clientHeight - row.offsetHeight) / 2;
}

function renderEpisodes(pattern) {
  const rows = entries.map((entry, index) => {
    const row = pageTemplate.content.firstElementChild.cloneNode(true);
    row.dataset.index = String(index);
    row.title = `${entry.title}\n${entry.url}`;
    row.querySelector(".link-badge").textContent = entry.label;
    row.querySelector(".link-title").textContent = entry.title;
    row.querySelector(".link-duration").textContent = formatDuration(entry.duration);
    entry.row = row;
    return row;
  });
  pageList.replaceChildren(...rows);
  episodeCount.textContent = String(entries.length);
  linkPattern.textContent = `${pattern}序号`;
  filterInput.value = "";
  applyFilter();
}

/** 选中一个链接：视频下方显示它的链接，播放按钮改为预览它。 */
function select(index) {
  entries[current]?.row?.classList.remove("selected");
  current = index;
  const entry = entries[index];
  entry.row?.classList.add("selected");
  currentLabel.textContent = `${entry.label}　${entry.title}`;
  currentUrl.value = entry.url;
  if (!stage.classList.contains("active")) setStage("idle");
}

/** 按筛选条件显示分 P；“复制全部”复制的是当前显示的分 P。 */
function applyFilter() {
  const keyword = filterInput.value.trim().toLowerCase();
  const range = PAGE_RANGE.exec(keyword);
  const [low, high] = range ? [Number(range[1]), Number(range[2])].sort((a, b) => a - b) : [];
  let visible = 0;
  for (const entry of entries) {
    const matched = range
      ? entry.page >= low && entry.page <= high
      : !keyword ||
        entry.title.toLowerCase().includes(keyword) ||
        [String(entry.page), `p${entry.page}`].includes(keyword);
    entry.row.hidden = !matched;
    if (matched) visible += 1;
  }
  copyAllButton.textContent = keyword ? `复制 ${visible} 条` : "复制全部";
  copyAllButton.disabled = visible === 0;
}

function copiedMessage(index) {
  return entries.length > 1 ? `已复制 ${entries[index].label} 的链接` : "已复制链接";
}

async function copy(text, message) {
  try {
    await writeClipboard(text);
    showToast(message);
  } catch {
    showToast("复制失败，请检查浏览器是否允许访问剪贴板", true);
  }
}

async function writeClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return;
  } catch {
    // 通过 http:// 访问时浏览器不提供 Clipboard API，退回到选中文本后执行复制命令。
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.className = "offscreen";
  document.body.append(textarea);
  textarea.select();
  textarea.setSelectionRange(0, text.length);
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("复制失败");
}

function showToast(message, isError = false) {
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, isError ? 4000 : 2000);
}

function setBusy(busy) {
  submitButton.disabled = busy;
  submitButton.textContent = busy ? "查询中…" : "生成链接";
}

/**
 * 视频区域的四种状态：idle（封面与播放按钮）、loading、playing、error。
 * 除 idle 外都视为正在预览：窄屏时视频吸附在屏幕顶部（见 style.css 中的 .stage.active）。
 */
function setStage(state, message = "") {
  const playing = state === "playing";
  stage.classList.toggle("active", state !== "idle");
  player.hidden = !playing;
  cover.hidden = playing || !cover.getAttribute("src");
  overlay.hidden = playing;
  playButton.hidden = state === "loading";
  stopButton.hidden = state === "idle";
  stageCaption.textContent = state === "idle" ? idleCaption() : message;
  stageCaption.classList.toggle("error", state === "error");
}

function idleCaption() {
  const entry = entries[current];
  if (entry.live) return "预览直播";
  return entries.length > 1 ? `预览 ${entry.label}　${entry.title}` : "预览视频";
}

async function preview() {
  stopPreview();
  const id = previewId;
  const entry = entries[current];
  setStage("loading", "正在获取播放地址…");
  if (entry.row) revealBelowStage(entry.row);
  let url;
  let Hls = null;
  try {
    url = await resolveMediaUrl(entry.url);
    // Safari 等浏览器原生支持 HLS，其余浏览器借助 hls.js 播放直播流。
    if (entry.live && !player.canPlayType(HLS_MIME_TYPE)) Hls = await loadHls();
  } catch (error) {
    if (id === previewId) setStage("error", error.message);
    return;
  }
  // 等待期间用户可能已开始新的预览或查询，此时放弃本次结果，避免两次预览争用播放器。
  if (id !== previewId) return;
  player.poster = cover.getAttribute("src") ?? "";
  if (Hls) {
    playWithHls(Hls, url);
  } else {
    player.src = url;
  }
  setStage("playing");
  // 浏览器可能禁止自动播放，此时由用户点击播放按钮即可。
  player.play().catch(() => {});
}

function stopPreview() {
  previewId += 1;
  hls?.destroy();
  hls = null;
  player.pause();
  player.removeAttribute("src");
  player.load();
  if (entries.length) setStage("idle");
}

/**
 * 窄屏时视频吸附在屏幕顶部，可能盖住刚点击的分 P：把页面向上滚一点，让它露在视频下方。
 * 宽屏时视频与选集左右并排，不会重叠。
 */
function revealBelowStage(row) {
  const screen = stage.getBoundingClientRect();
  const rect = row.getBoundingClientRect();
  const sideBySide = rect.right <= screen.left || rect.left >= screen.right;
  const covered = screen.bottom - rect.top;
  if (!sideBySide && covered > 0 && rect.bottom > screen.top) window.scrollBy(0, -(covered + 8));
}

/**
 * 请求本服务的链接并返回重定向后的媒体直链，只读取响应头，不下载媒体内容。
 * 播放器直接使用直链：拖动进度条、刷新直播列表时不会反复请求本服务而耗尽限流配额。
 */
async function resolveMediaUrl(link) {
  const controller = new AbortController();
  try {
    const response = await fetch(link, { signal: controller.signal });
    if (!response.redirected) throw new ServiceError(await readError(response));
    return response.url;
  } catch (error) {
    if (error instanceof ServiceError) throw error;
    // 媒体服务器不允许跨域读取时拿不到直链，交给播放器自己跟随重定向。
    return link;
  } finally {
    controller.abort();
  }
}

async function loadHls() {
  const { default: Hls } = await import("./vendor/hls.js/hls.light.min.mjs");
  if (!Hls.isSupported()) throw new Error("当前浏览器不支持播放直播流");
  return Hls;
}

function playWithHls(Hls, url) {
  // 页面的内容安全策略不允许 blob: Worker；预览时在主线程转封装即可。
  hls = new Hls({ enableWorker: false });
  hls.on(Hls.Events.ERROR, (_event, data) => {
    if (data.fatal) setStage("error", `直播流播放失败（${data.details}）`);
  });
  hls.loadSource(url);
  hls.attachMedia(player);
}

async function fetchJson(path) {
  let response;
  try {
    response = await fetch(path);
  } catch {
    throw new Error("无法连接服务器，请检查网络");
  }
  if (!response.ok) throw new ServiceError(await readError(response));
  return response.json();
}

async function readError(response) {
  try {
    const { error } = await response.json();
    if (typeof error === "string") return error;
  } catch {
    // 不是本服务的 JSON 错误响应，使用下面的通用说明。
  }
  return `请求失败（HTTP ${response.status}）`;
}

/** 本服务上的绝对地址：相对于页面地址解析，因此与页面位于同一域名与路径前缀之下。 */
function serviceUrl(path) {
  return new URL(path, document.baseURI).href;
}

function formatDuration(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}
