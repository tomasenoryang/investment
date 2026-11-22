const svgNS = "http://www.w3.org/2000/svg";
const dialog = document.querySelector(".chart-dialog");
const dialogChart = document.querySelector("#dialog-chart");
const dataCache = new Map();

function readChart(url) {
  if (!dataCache.has(url)) {
    const pending = fetch(url).then(async (response) => {
      if (!response.ok) throw new Error("无法读取图表数据");
      const documentSvg = new DOMParser().parseFromString(await response.text(), "image/svg+xml");
      const data = JSON.parse(documentSvg.getElementById("chart-data").textContent);
      const box = documentSvg.documentElement.getAttribute("viewBox");
      return { ...data, box, width: Number(box.split(" ")[2]), height: Number(box.split(" ")[3]) };
    }).catch((error) => {
      dataCache.delete(url);
      throw error;
    });
    dataCache.set(url, pending);
    if (dataCache.size > 48) dataCache.delete(dataCache.keys().next().value);
  }
  return dataCache.get(url);
}

function nearestPoint(points, x) {
  let low = 0;
  let high = points.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (points[middle][0] < x) low = middle + 1;
    else high = middle;
  }
  return low > 0 && x - points[low - 1][0] <= points[low][0] - x ? low - 1 : low;
}

function enableChart(img) {
  const surface = document.createElement("div");
  surface.className = "chart-surface";
  surface.tabIndex = 0;
  surface.setAttribute("aria-label", "曲线图，左右方向键查看数据点");
  const interaction = document.createElement("div");
  interaction.className = "chart-interaction";
  img.before(interaction);
  interaction.append(surface);
  const overlay = document.createElementNS(svgNS, "svg");
  overlay.classList.add("chart-focus");
  overlay.setAttribute("aria-hidden", "true");
  const lines = document.createElementNS(svgNS, "path");
  const point = document.createElementNS(svgNS, "circle");
  point.setAttribute("r", "5");
  overlay.append(lines, point);
  const tooltip = document.createElement("div");
  tooltip.className = "chart-tooltip";
  tooltip.setAttribute("aria-live", "polite");
  // Show the footer of the same local SVG below the live readout.
  const notes = document.createElement("div");
  notes.className = "chart-notes";
  notes.setAttribute("aria-hidden", "true");
  const notesImage = new Image();
  notesImage.alt = "";
  notes.append(notesImage);
  interaction.append(tooltip, notes);
  surface.append(img, overlay);
  let url;
  let data;
  let cursor;
  let selected = -1;

  function clearFocus() {
    lines.removeAttribute("d");
    point.style.display = "none";
    tooltip.textContent = "";
  }

  function show(index) {
    selected = index;
    const [x, y, day, value] = data.points[index];
    const [left, top, right, bottom] = data.plot;
    lines.setAttribute("d", `M${x} ${top}V${bottom} M${left} ${y}H${right}`);
    point.setAttribute("cx", x);
    point.setAttribute("cy", y);
    point.style.display = "";
    tooltip.textContent = `${day}　${data.metric} ${value.toFixed(data.digits)} ${data.unit}`;
    if (data.comparison) tooltip.textContent += `　${data.comparison} ${data.points[index][4].toFixed(2)} 点`;
    if (data.tracking) {
      const tracking = data.points[index][5];
      tooltip.textContent += Number.isFinite(tracking)
        ? `　累计较指数 ${tracking >= 0 ? "+" : ""}${tracking.toFixed(2)} 个百分点`
        : "　指数无同日数据";
    }
  }

  function renderCursor() {
    if (!data || !cursor || url !== img.src) return;
    const rect = img.getBoundingClientRect();
    const x = (cursor.x - rect.left) / rect.width * data.width;
    const y = (cursor.y - rect.top) / rect.height * data.height;
    const [left, top, right, bottom] = data.plot;
    const last = data.points.at(-1);
    const dx = (x - last[0]) * rect.width / data.width;
    const dy = (y - last[1]) * rect.height / data.height;
    if (Math.hypot(dx, dy) <= 6) {
      show(data.points.length - 1);
    } else if (x >= left && x <= right + 8 * data.width / rect.width && y >= top && y <= bottom) {
      show(nearestPoint(data.points, Math.min(x, right)));
    } else {
      clearFocus();
    }
  }

  async function load() {
    if (!img.getAttribute("src")) return;
    const requested = img.src;
    if (requested !== url) {
      url = requested;
      data = null;
      selected = -1;
      clearFocus();
    }
    if (data) return data;
    try {
      const next = await readChart(requested);
      if (requested !== img.src) return;
      data = next;
      overlay.setAttribute("viewBox", data.box);
      interaction.style.setProperty("--axis-end", (data.plot[3] + 36) / data.width * 100 + "cqw");
      return data;
    } catch {
      return undefined;
    }
  }

  clearFocus();
  function onImageLoad() {
    if (img.currentSrc) notesImage.src = img.currentSrc;
    if (img.src !== url) {
      data = null;
      selected = -1;
      clearFocus();
    }
    load();
  }
  img.addEventListener("load", onImageLoad);
  if (img.complete && img.naturalWidth) onImageLoad();
  function track(event) {
    cursor = { x: event.clientX, y: event.clientY };
    if (data && url === img.src) renderCursor();
    else load().then(renderCursor);
  }
  surface.addEventListener("pointermove", track);
  surface.addEventListener("pointerdown", track);
  surface.addEventListener("pointerleave", () => { cursor = null; clearFocus(); });
  surface.addEventListener("blur", clearFocus);
  surface.addEventListener("keydown", async (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    if (!await load() || document.activeElement !== surface) return;
    const next = selected < 0 ? (event.key === "ArrowLeft" ? data.points.length - 1 : 0)
      : selected + (event.key === "ArrowLeft" ? -1 : 1);
    show(Math.max(0, Math.min(data.points.length - 1, next)));
  });
}

function enableFigure(figure) {
  const img = figure.querySelector("img");
  const expand = document.createElement("button");
  expand.type = "button";
  expand.className = "chart-expand";
  expand.textContent = "⛶";
  expand.title = "放大查看";
  expand.setAttribute("aria-label", "放大查看");
  figure.append(expand);
  enableChart(img);
  expand.addEventListener("click", () => {
    if (!img.getAttribute("src")) return;
    const enlarged = new Image();
    enlarged.src = img.src;
    enlarged.alt = img.alt;
    dialogChart.replaceChildren(enlarged);
    enableChart(enlarged);
    dialog.showModal();
  });
}
document.querySelectorAll("main figure").forEach(enableFigure);
dialog.addEventListener("close", () => dialogChart.replaceChildren());
