// Cores reproduzidas da configuração da aba Mapa_GN do Power BI.
const COLORS = { "Atendido": "#B70815", "Em expansão": "#F2A900", "Não atendido": "#03BE60" };
const PAGE_SIZE = 35, WIDTH = 840, HEIGHT = 720, HIT_SCALE = 2;
const state = {
  municipalities: window.MUNICIPIOS_GN_DATA || [], byCode: new Map(), filtered: [], allowed: new Set(),
  page: 1, selected: null, statusFilter: "", transform: { x: 0, y: 0, k: 1 }, groupPaths: {}, filteredPaths: {}, statePath: null, hitImage: null, labels: { municipalities: [], states: [] }
};
const ids = ["regionSelect", "ufSelect", "mesoregionSelect", "municipalitySelect", "clearFilters", "totalCount", "attendedCount", "expansionCount",
  "unattendedCount", "municipalityRows", "tableSummary", "pageInfo", "prevPage", "nextPage", "mapCanvas", "hitCanvas",
  "mapWrap", "tooltip", "mapLoading", "sourceStatus", "selectedCard", "selectedStatus", "selectedCity", "selectedConcession",
  "closeCard", "zoomIn", "zoomOut", "comgasMapButton"];
const el = Object.fromEntries(ids.map(id => [id, document.getElementById(id)]));
const statusButtons = [...document.querySelectorAll("[data-status-filter]")];
const ctx = el.mapCanvas.getContext("2d");
el.hitCanvas.width = WIDTH * HIT_SCALE; el.hitCanvas.height = HEIGHT * HIT_SCALE;
const hitCtx = el.hitCanvas.getContext("2d", { willReadFrequently: true });
const normalize = value => String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
const formatNumber = n => new Intl.NumberFormat("pt-BR").format(n);
const sortPt = (a, b) => String(a).localeCompare(String(b), "pt-BR");
const UF_NAMES = {
  AC: "Acre", AL: "Alagoas", AP: "Amapá", AM: "Amazonas", BA: "Bahia", CE: "Ceará", DF: "Distrito Federal",
  ES: "Espírito Santo", GO: "Goiás", MA: "Maranhão", MT: "Mato Grosso", MS: "Mato Grosso do Sul", MG: "Minas Gerais",
  PA: "Pará", PB: "Paraíba", PR: "Paraná", PE: "Pernambuco", PI: "Piauí", RJ: "Rio de Janeiro",
  RN: "Rio Grande do Norte", RS: "Rio Grande do Sul", RO: "Rondônia", RR: "Roraima", SC: "Santa Catarina",
  SP: "São Paulo", SE: "Sergipe", TO: "Tocantins"
};

async function boot() {
  try {
    if (!state.municipalities.length || !window.MAPA_PATHS || !window.MAPA_LOOKUP || !window.MAPA_ESTADOS) throw new Error("Os arquivos publicados do mapa não foram encontrados.");
    state.byCode = new Map(state.municipalities.map(item => [String(item.codigo_ibge), item]));
    el.sourceStatus.textContent = `Base publicada • ${formatNumber(state.municipalities.length)} municípios • referência ${window.MUNICIPIOS_GN_META?.atualizado_em || "não informada"}`;
    populateFilters();
    buildGroupPaths();
    buildLabelPositions();
    state.hitImage = await loadImage("Arquivos do Mapa Brasil/Dados/mapa-hit.png");
    applyFilters(); bindEvents(); el.mapLoading.hidden = true;
  } catch (error) {
    el.mapLoading.textContent = error.message; el.sourceStatus.textContent = "Falha ao carregar os arquivos publicados";
  }
}

function loadImage(src) { return new Promise((resolve, reject) => { const image = new Image(); image.onload = () => resolve(image); image.onerror = reject; image.src = src; }); }
function optionScope(excludeField = "") {
  return state.municipalities.filter(item => {
    return (excludeField === "regiao" || !el.regionSelect.value || item.regiao === el.regionSelect.value)
      && (excludeField === "uf" || !el.ufSelect.value || item.uf === el.ufSelect.value)
      && (excludeField === "mesorregiao" || !el.mesoregionSelect.value || item.mesorregiao === el.mesoregionSelect.value)
      && (excludeField === "codigo_ibge" || !el.municipalitySelect.value || String(item.codigo_ibge) === el.municipalitySelect.value);
  });
}
function uniqueValues(field, source = state.municipalities) { return [...new Set(source.map(item => item[field]).filter(Boolean))].sort(sortPt); }
function fillSelect(select, values, firstLabel, getValue = value => value, getLabel = value => value) {
  select.replaceChildren(new Option(firstLabel, ""));
  values.forEach(value => select.append(new Option(getLabel(value), getValue(value))));
}
function populateFilters() {
  updateFilterOptions();
}
function updateSelectOptions(select, values, firstLabel, selectedValue, getValue = value => value, getLabel = value => value) {
  fillSelect(select, values, firstLabel, getValue, getLabel);
  select.value = [...select.options].some(option => option.value === selectedValue) ? selectedValue : "";
}
function updateFilterOptions() {
  const selected = {
    region: el.regionSelect.value,
    uf: el.ufSelect.value,
    mesoregion: el.mesoregionSelect.value,
    municipality: el.municipalitySelect.value
  };

  updateSelectOptions(el.regionSelect, uniqueValues("regiao"), "Todos", selected.region);
  const region = el.regionSelect.value;

  const byRegion = state.municipalities.filter(item => !region || item.regiao === region);
  updateSelectOptions(el.ufSelect, uniqueValues("uf", byRegion), "Todos", selected.uf);
  const uf = el.ufSelect.value;

  const byRegionUf = byRegion.filter(item => !uf || item.uf === uf);
  updateSelectOptions(el.mesoregionSelect, uniqueValues("mesorregiao", byRegionUf), "Todos", selected.mesoregion);
  const mesoregion = el.mesoregionSelect.value;

  const byMeso = byRegionUf.filter(item => !mesoregion || item.mesorregiao === mesoregion);
  const cities = byMeso.sort((a, b) => sortPt(`${a.municipio} ${a.uf}`, `${b.municipio} ${b.uf}`));
  updateSelectOptions(el.municipalitySelect, cities, "Todos", selected.municipality, item => String(item.codigo_ibge), item => item.municipio);
}
function updateStatusButtons() {
  statusButtons.forEach(button => {
    const active = button.dataset.statusFilter === state.statusFilter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}
function buildGroupPaths() {
  const grouped = { "Atendido": [], "Em expansão": [], "Não atendido": [] };
  state.municipalities.forEach(item => { const path = window.MAPA_PATHS[item.codigo_ibge]; if (path && grouped[item.status]) grouped[item.status].push(path); });
  Object.entries(grouped).forEach(([status, paths]) => state.groupPaths[status] = new Path2D(paths.join("")));
  state.statePath = new Path2D(Object.values(window.MAPA_ESTADOS).join(""));
}
function buildFilteredPaths() {
  const grouped = { "Atendido": [], "Em expansão": [], "Não atendido": [] };
  state.filtered.forEach(item => { const path = window.MAPA_PATHS[item.codigo_ibge]; if (path && grouped[item.status]) grouped[item.status].push(path); });
  state.filteredPaths = {}; Object.entries(grouped).forEach(([status, paths]) => state.filteredPaths[status] = new Path2D(paths.join("")));
}
function pathBounds(path) {
  const values = String(path || "").match(/-?\d+(?:\.\d+)?/g)?.map(Number) || [];
  if (values.length < 2) return null;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (let i = 0; i < values.length - 1; i += 2) {
    const x = values[i], y = values[i + 1];
    minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
  }
  return { x: (minX + maxX) / 2, y: (minY + maxY) / 2, area: Math.max(1, (maxX - minX) * (maxY - minY)) };
}
function buildLabelPositions() {
  const statesByCode = new Map();
  state.municipalities.forEach(item => {
    const stateCode = String(item.codigo_ibge).slice(0, 2);
    if (!statesByCode.has(stateCode)) statesByCode.set(stateCode, { uf: item.uf, name: UF_NAMES[item.uf] || item.uf });
  });
  state.labels.states = Object.entries(window.MAPA_ESTADOS).map(([stateCode, path]) => {
    const bounds = pathBounds(path), info = statesByCode.get(stateCode);
    return bounds && info ? { ...bounds, uf: info.uf, name: info.name } : null;
  }).filter(Boolean);
  state.labels.municipalities = state.municipalities.map(item => {
    const bounds = pathBounds(window.MAPA_PATHS[item.codigo_ibge]);
    return bounds ? { ...bounds, code: String(item.codigo_ibge), name: item.municipio, uf: item.uf, status: item.status } : null;
  }).filter(Boolean).sort((a, b) => b.area - a.area);
}
function screenPoint(label) {
  return { x: label.x * state.transform.k + state.transform.x, y: label.y * state.transform.k + state.transform.y };
}
function labelIsVisible(label, margin = 32) {
  const point = screenPoint(label);
  return point.x >= -margin && point.x <= WIDTH + margin && point.y >= -margin && point.y <= HEIGHT + margin;
}
function boxesOverlap(a, b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}
function drawLabelText(text, label, placed, { font, color, maxWidth, halo = "rgba(255,255,255,.92)" }) {
  const point = screenPoint(label);
  ctx.font = font;
  let display = text;
  while (ctx.measureText(display).width > maxWidth && display.length > 8) display = `${display.slice(0, -2)}…`;
  const width = ctx.measureText(display).width + 10;
  const fontSize = Number(font.match(/(\d+)px/)?.[1] || 11);
  const height = fontSize + 8;
  const box = { x: point.x - width / 2, y: point.y - height / 2, w: width, h: height };
  if (placed.some(other => boxesOverlap(box, other))) return false;
  placed.push(box);
  ctx.lineWidth = 4;
  ctx.strokeStyle = halo;
  ctx.strokeText(display, point.x, point.y);
  ctx.fillStyle = color;
  ctx.fillText(display, point.x, point.y);
  return true;
}
function drawMapLabels() {
  const zoom = state.transform.k;
  const placed = [];
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";

  if (zoom >= 1.7) {
    state.labels.states
      .filter(label => (!el.ufSelect.value || label.uf === el.ufSelect.value) && labelIsVisible(label, 70))
      .forEach(label => drawLabelText(`${label.name} - ${label.uf}`, label, placed, { font: "700 12px Segoe UI, Arial, sans-serif", color: "#102a43", maxWidth: 130 }));
  }

  if (zoom >= 4.8) {
    const maxLabels = zoom >= 10 ? 220 : zoom >= 7 ? 140 : 80;
    let drawn = 0;
    state.labels.municipalities
      .filter(label => state.allowed.has(label.code) && labelIsVisible(label, 45))
      .sort((a, b) => (state.selected?.codigo_ibge === a.code ? -1 : state.selected?.codigo_ibge === b.code ? 1 : b.area - a.area))
      .some(label => {
        if (drawn >= maxLabels) return true;
        const ok = drawLabelText(`${label.name} - ${label.uf}`, label, placed, { font: "600 11px Segoe UI, Arial, sans-serif", color: "#102a43", maxWidth: 115 });
        if (ok) drawn++;
        return false;
      });
  }
  ctx.restore();
}
function renderMap() {
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, WIDTH, HEIGHT);
  ctx.setTransform(state.transform.k, 0, 0, state.transform.k, state.transform.x, state.transform.y);
  const isFiltered = state.filtered.length !== state.municipalities.length;
  Object.entries(state.groupPaths).forEach(([status, path]) => { ctx.globalAlpha = isFiltered ? .11 : 1; ctx.fillStyle = COLORS[status]; ctx.fill(path, "evenodd"); });
  if (isFiltered) Object.entries(state.filteredPaths).forEach(([status, path]) => { ctx.globalAlpha = 1; ctx.fillStyle = COLORS[status]; ctx.fill(path, "evenodd"); });
  ctx.globalAlpha = 1; ctx.strokeStyle = "#ffffff"; ctx.lineWidth = .38 / state.transform.k;
  Object.values(state.groupPaths).forEach(path => ctx.stroke(path));
  ctx.strokeStyle = "#29485e"; ctx.lineWidth = 1.25 / state.transform.k; ctx.stroke(state.statePath);
  if (state.selected && window.MAPA_PATHS[state.selected.codigo_ibge]) { ctx.strokeStyle = "#102a43"; ctx.lineWidth = 1.6 / state.transform.k; ctx.stroke(new Path2D(window.MAPA_PATHS[state.selected.codigo_ibge])); }
  drawMapLabels();
  hitCtx.setTransform(1, 0, 0, 1, 0, 0); hitCtx.clearRect(0, 0, WIDTH * HIT_SCALE, HEIGHT * HIT_SCALE);
  hitCtx.setTransform(HIT_SCALE * state.transform.k, 0, 0, HIT_SCALE * state.transform.k, HIT_SCALE * state.transform.x, HIT_SCALE * state.transform.y);
  hitCtx.drawImage(state.hitImage, 0, 0, WIDTH, HEIGHT);
}
function matches(item) {
  return (!el.regionSelect.value || item.regiao === el.regionSelect.value)
    && (!el.ufSelect.value || item.uf === el.ufSelect.value)
    && (!el.mesoregionSelect.value || item.mesorregiao === el.mesoregionSelect.value)
    && (!el.municipalitySelect.value || String(item.codigo_ibge) === el.municipalitySelect.value)
    && (!state.statusFilter || item.status === state.statusFilter);
}
function applyFilters() {
  state.filtered = state.municipalities.filter(matches).sort((a, b) => a.municipio.localeCompare(b.municipio, "pt-BR"));
  state.allowed = new Set(state.filtered.map(item => String(item.codigo_ibge))); state.page = 1; buildFilteredPaths(); updateCounters(); renderTable(); renderMap();
}
function updateCounters() {
  const counts = { "Atendido": 0, "Em expansão": 0, "Não atendido": 0 }; state.filtered.forEach(item => counts[item.status] = (counts[item.status] || 0) + 1);
  if (el.totalCount) el.totalCount.textContent = formatNumber(state.filtered.length);
  if (el.attendedCount) el.attendedCount.textContent = formatNumber(counts["Atendido"] || 0);
  if (el.expansionCount) el.expansionCount.textContent = formatNumber(counts["Em expansão"] || 0);
  if (el.unattendedCount) el.unattendedCount.textContent = formatNumber(counts["Não atendido"] || 0);
  el.tableSummary.textContent = `${formatNumber(state.filtered.length)} municípios encontrados`;
}
function renderTable() {
  const pages = Math.max(1, Math.ceil(state.filtered.length / PAGE_SIZE)); state.page = Math.min(state.page, pages); const start = (state.page - 1) * PAGE_SIZE;
  el.municipalityRows.replaceChildren(...state.filtered.slice(start, start + PAGE_SIZE).map(item => { const row = document.createElement("tr"); row.innerHTML = `<td>${escapeHtml(item.municipio)}</td><td>${item.uf}</td><td><span class="mini-status" style="--status-color:${COLORS[item.status]}">${escapeHtml(item.status)}</span></td>`; row.addEventListener("click", () => selectMunicipality(item)); return row; }));
  el.pageInfo.textContent = `${state.page} de ${pages}`; el.prevPage.disabled = state.page <= 1; el.nextPage.disabled = state.page >= pages;
}
function selectMunicipality(item) { state.selected = item; el.selectedCard.hidden = false; el.selectedStatus.textContent = item.status; el.selectedStatus.style.background = COLORS[item.status]; el.selectedCity.textContent = `${item.municipio} — ${item.uf}`; el.selectedConcession.textContent = `Concessionária: ${item.concessionaria || "Não informada"}`; renderMap(); }
function itemAt(event) {
  const rect = el.mapCanvas.getBoundingClientRect(); const x = Math.max(0, Math.min(WIDTH * HIT_SCALE - 1, Math.floor((event.clientX - rect.left) * WIDTH * HIT_SCALE / rect.width))); const y = Math.max(0, Math.min(HEIGHT * HIT_SCALE - 1, Math.floor((event.clientY - rect.top) * HEIGHT * HIT_SCALE / rect.height)));
  const pixel = hitCtx.getImageData(x, y, 1, 1).data; const index = pixel[0] + (pixel[1] << 8) + (pixel[2] << 16) - 1; const code = index >= 0 ? window.MAPA_LOOKUP[index] : null; const item = code ? state.byCode.get(code) : null; return item && state.allowed.has(code) ? item : null;
}
function showTooltip(event, item) { if (!item) { el.tooltip.hidden = true; return; } el.tooltip.innerHTML = `<strong>${escapeHtml(item.municipio)} — ${item.uf}</strong>${escapeHtml(item.status)}<br>${escapeHtml(item.concessionaria || "Sem concessionária informada")}`; el.tooltip.hidden = false; const rect = el.mapWrap.getBoundingClientRect(); el.tooltip.style.left = `${Math.min(event.clientX - rect.left + 12, rect.width - 205)}px`; el.tooltip.style.top = `${Math.max(8, event.clientY - rect.top - 58)}px`; }
function escapeHtml(value) { const div = document.createElement("div"); div.textContent = String(value ?? ""); return div.innerHTML; }
function setZoom(k, x = state.transform.x, y = state.transform.y) {
  state.transform.k = Math.max(1, Math.min(24, k));
  state.transform.x = x;
  state.transform.y = y;
  renderMap();
}
function zoomAt(clientX, clientY, factor) {
  const rect = el.mapCanvas.getBoundingClientRect();
  const nextK = Math.max(1, Math.min(24, state.transform.k * factor));
  const px = (clientX - rect.left) * WIDTH / rect.width;
  const py = (clientY - rect.top) * HEIGHT / rect.height;
  const mapX = (px - state.transform.x) / state.transform.k;
  const mapY = (py - state.transform.y) / state.transform.k;
  setZoom(nextK, px - mapX * nextK, py - mapY * nextK);
}
function zoomAtCenter(factor) {
  const rect = el.mapCanvas.getBoundingClientRect();
  zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, factor);
}
function openConcessionairesMaps() {
  window.location.href = "mapaconcessionarias.html";
}
function bindEvents() {
  [el.regionSelect, el.ufSelect, el.mesoregionSelect, el.municipalitySelect].forEach(select => select.addEventListener("change", applyFilters));
  statusButtons.forEach(button => button.addEventListener("click", () => { state.statusFilter = state.statusFilter === button.dataset.statusFilter ? "" : button.dataset.statusFilter; updateStatusButtons(); applyFilters(); }));
  el.clearFilters.addEventListener("click", () => { el.regionSelect.value = ""; el.ufSelect.value = ""; el.mesoregionSelect.value = ""; el.municipalitySelect.value = ""; state.statusFilter = ""; updateStatusButtons(); applyFilters(); }); el.prevPage.addEventListener("click", () => { state.page--; renderTable(); }); el.nextPage.addEventListener("click", () => { state.page++; renderTable(); });
  el.closeCard.addEventListener("click", () => { el.selectedCard.hidden = true; state.selected = null; renderMap(); }); el.zoomIn.addEventListener("click", () => zoomAtCenter(1.6)); el.zoomOut.addEventListener("click", () => zoomAtCenter(1 / 1.6)); el.comgasMapButton.addEventListener("click", openConcessionairesMaps);
  el.mapCanvas.addEventListener("wheel", event => { event.preventDefault(); zoomAt(event.clientX, event.clientY, event.deltaY < 0 ? 1.28 : 1 / 1.28); }, { passive: false }); let drag = null;
  el.mapCanvas.addEventListener("pointerdown", event => { drag = { x: event.clientX, y: event.clientY, tx: state.transform.x, ty: state.transform.y }; el.mapCanvas.setPointerCapture(event.pointerId); });
  el.mapCanvas.addEventListener("pointermove", event => { if (drag && state.transform.k > 1) setZoom(state.transform.k, drag.tx + event.clientX - drag.x, drag.ty + event.clientY - drag.y); else showTooltip(event, itemAt(event)); });
  el.mapCanvas.addEventListener("pointerup", event => { if (drag && Math.abs(event.clientX - drag.x) < 4 && Math.abs(event.clientY - drag.y) < 4) { const item = itemAt(event); if (item) selectMunicipality(item); } drag = null; }); el.mapCanvas.addEventListener("pointerleave", () => { el.tooltip.hidden = true; drag = null; });
}
boot();





