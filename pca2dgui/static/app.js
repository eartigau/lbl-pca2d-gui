/*
 * The LBL window: the page. It holds the window's state (saved on the server,
 * ~/.lbl_pca2d_gui.json), draws what the server reads from LBL and from the
 * data folder, and hands the server what to build and run. No framework:
 * one file, plain DOM and SVG.
 */
'use strict';

const $ = (id) => document.getElementById(id);
const SERIES = ['--series-1', '--series-2', '--series-3', '--series-4',
                '--series-5', '--series-6', '--series-7', '--series-8'];
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const SCATTER_COLOURED = 3;   // the palette's all-pairs cap (dataviz validator)
const HIST_COLOURED = 8;      // its adjacent-pair cap
const LOG_LINES = 5000;       // lines kept on the page (the log file keeps all)

const DEFAULTS = {
  lang: 'en', theme: 'light', tab: 'targets', data_dir: '', instrument: '', source: '',
  python: '', ticked: [], hidden_instruments: [], sort: { key: 'name', dir: 1 },
  comparison: {}, teff: {}, lbl: {}, pca2d_on: true, pca2d: {},
  extra: {}, pca2d_extra: {},
  skip_pca2d: null, min_rjd: null, max_rjd: null, resproj: false,
  name: '', name_auto: true,
};
const S = JSON.parse(JSON.stringify(DEFAULTS));
let T = {};
let INSTRUMENTS = [];
let OPTIONS = [];
let SWITCHES = [];
let TARGETS = [];
let BASES = [];
let TEMPLATES = [];
let VETTED = [];
let POINTS = {};
let wrapEdited = false;
let selectedJob = null;
let stream = null;
let logLast = null;
let scanTimer = null;
let rescanned = false;

// ── plumbing ────────────────────────────────────────────────────────────
const api = {
  async get(path, params) {
    const url = new URL(path, location.origin);
    Object.entries(params || {}).forEach(([k, v]) => url.searchParams.set(k, v ?? ''));
    const response = await fetch(url);
    return response.json();
  },
  async post(path, body) {
    const response = await fetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    const data = await response.json().catch(() => ({}));
    data._status = response.status;
    return data;
  },
};

function t(key, ...args) {
  let text = T[key] ?? key;
  args.forEach((arg) => { text = text.replace('%s', arg); });
  return text;
}

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([k, v]) => {
    if (v === null || v === undefined || v === false) return;
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : v);
  });
  children.flat().forEach((child) => {
    if (child === null || child === undefined || child === false) return;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  });
  return node;
}

let saveTimer = null;
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => api.post('/api/state', S), 400);
}

const fmt = (x, digits = 1) => (x === null || x === undefined || Number.isNaN(x) ? '' : Number(x).toFixed(digits));
function human(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let value = bytes;
  while (value >= 1000 && i < units.length - 1) { value /= 1000; i += 1; }
  return `${value.toFixed(i ? 1 : 0)} ${units[i]}`;
}
function mjdDate(mjd) {
  if (mjd === null || mjd === undefined) return '';
  return new Date((mjd - 40587) * 86400000).toISOString().slice(0, 10);
}
function when(seconds) {
  if (!seconds) return '';
  const date = new Date(seconds * 1000);
  return date.toISOString().slice(0, 16).replace('T', ' ');
}
function took(start, end) {
  if (!start) return '';
  const total = Math.round(((end || Date.now() / 1000) - start));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h} h ${String(m).padStart(2, '0')} min` : m ? `${m} min ${String(s).padStart(2, '0')} s` : `${s} s`;
}
function fileLink(path, text) {
  return el('a', { href: `/file?path=${encodeURIComponent(path)}`, target: '_blank', text: text || t('open') });
}
function relative(path) {
  const root = (S.data_dir || '').replace(/\/$/, '') + '/';
  return path && path.startsWith(root) ? path.slice(root.length) : path;
}

// ── tooltip (data-tip) ──────────────────────────────────────────────────
function tip(event, html) {
  const box = $('tooltip');
  if (!html) { box.hidden = true; return; }
  box.innerHTML = html;
  box.hidden = false;
  const pad = 14;
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  const rect = box.getBoundingClientRect();
  if (x + rect.width > window.innerWidth - 8) x = event.clientX - rect.width - pad;
  if (y + rect.height > window.innerHeight - 8) y = event.clientY - rect.height - pad;
  box.style.left = `${x}px`;
  box.style.top = `${y}px`;
}
document.addEventListener('mouseover', (event) => {
  const target = event.target.closest('[data-tip]');
  if (target) tip(event, target.dataset.tip);
});
document.addEventListener('mousemove', (event) => {
  const target = event.target.closest('[data-tip]');
  if (target) tip(event, target.dataset.tip);
});
document.addEventListener('mouseout', (event) => {
  if (event.target.closest('[data-tip]')) tip(event, null);
});
const esc = (text) => String(text ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
// a help is plain text, a blank line between its paragraphs
const helpHtml = (text) => esc(text).replace(/\n\n/g, '<br><br>');
const info = (key) => el('span', { class: 'info', 'data-tip': helpHtml(t(key)), text: 'i' });
// an (i) inside a <label> explains it and does not tick or focus it
document.addEventListener('click', (event) => { if (event.target.closest('.info')) event.preventDefault(); });

function confirmBox(text) {
  return new Promise((resolve) => {
    $('modal_text').textContent = text;
    $('modal').hidden = false;
    const done = (answer) => {
      $('modal').hidden = true;
      $('modal_yes').onclick = null;
      $('modal_no').onclick = null;
      resolve(answer);
    };
    $('modal_yes').onclick = () => done(true);
    $('modal_no').onclick = () => done(false);
  });
}

// ── strings ─────────────────────────────────────────────────────────────
async function loadStrings() {
  T = await api.get('/api/strings', { lang: S.lang });
  document.documentElement.lang = S.lang;
  document.querySelectorAll('[data-t]').forEach((node) => { node.textContent = t(node.dataset.t); });
  document.querySelectorAll('[data-help]').forEach((node) => { node.textContent = 'i'; node.dataset.tip = helpHtml(t(`help_${node.dataset.help}`)); });
  $('lang').textContent = T.lang_switch;
  applyTheme();
  updateLaunch(null);
  $('skip_pca2d').replaceChildren(
    el('option', { value: '', text: t('skip_auto') }),
    el('option', { value: 'true', text: t('skip_keep') }),
    el('option', { value: 'false', text: t('skip_redo') }));
  $('skip_pca2d').value = S.skip_pca2d === null ? '' : String(S.skip_pca2d);
}

// ── theme ───────────────────────────────────────────────────────────────
const SUN = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const MOON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/></svg>';
function applyTheme() {
  document.documentElement.dataset.theme = S.theme;
  // the button offers the other theme
  const light = S.theme === 'light';
  $('theme').innerHTML = `${light ? MOON : SUN} <span>${t(light ? 'theme_dark' : 'theme_light')}</span>`;
}

async function switchTheme() {
  S.theme = S.theme === 'light' ? 'dark' : 'light';
  save();
  applyTheme();
  // the plots and swatches read their colours from the theme when drawn
  drawTargets();
  drawPlots();
  $('backdrop').classList.remove('ready');
  setBackdrop();
}

// ── tabs ────────────────────────────────────────────────────────────────
function showTab(name) {
  S.tab = name;
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.pane').forEach((p) => { p.hidden = p.id !== `pane-${name}`; });
  if (name === 'run') { if (!wrapEdited) build(); loadWrapList(); }
  if (name === 'runs') loadRuns();
  if (name === 'cleanup') measure();
  if (name === 'targets') drawPlots();
  save();
}

// ── instrument and source ───────────────────────────────────────────────
function fillInstruments() {
  const select = $('instrument');
  select.replaceChildren(...INSTRUMENTS.map((row) => el('option', { value: row.instrument, text: row.instrument })));
  if (!S.instrument && INSTRUMENTS.length) S.instrument = INSTRUMENTS[0].instrument;
  select.value = S.instrument;
  fillSources();
}
function sourcesOf(instrument) {
  return (INSTRUMENTS.find((row) => row.instrument === instrument) || { sources: [] }).sources;
}
function fillSources() {
  const sources = sourcesOf(S.instrument);
  $('source').replaceChildren(...sources.map((row) => el('option', { value: row.source, text: row.source })));
  if (!sources.find((row) => row.source === S.source)) S.source = sources.length ? sources[0].source : '';
  $('source').value = S.source;
}
function instrumentTelluclean() {
  const row = sourcesOf(S.instrument).find((r) => r.source === S.source);
  return row ? row.telluclean : false;
}
/* the LBL instrument a header's INSTRUME most likely is */
function guessInstrument(header) {
  const name = String(header || '').toUpperCase();
  const names = INSTRUMENTS.map((row) => row.instrument);
  if (names.includes(name)) return name;
  if (name.startsWith('NIRPS')) return 'NIRPS_HE';
  if (name === 'HARPS-N' || name === 'HARPN') return 'HARPSN';
  return null;
}

// ── targets ─────────────────────────────────────────────────────────────
async function loadTargets() {
  if (!S.data_dir) { TARGETS = []; drawTargets(); return; }
  const data = await api.get('/api/targets', { data_dir: S.data_dir });
  if (data.error) { $('scan_status').textContent = data.error; return; }
  TARGETS = data.targets || [];
  const scan = data.scan || {};
  if (scan.running && scan.data_dir) {
    $('scan_status').textContent = t('scanning', scan.done, scan.total);
  } else {
    const files = TARGETS.reduce((sum, row) => sum + (row.files || 0), 0);
    $('scan_status').textContent = TARGETS.length ? t('scan_done', TARGETS.length, files) : t('data_dir_hint');
  }
  if (!scan.running && scanTimer) { clearInterval(scanTimer); scanTimer = null; }
  // spectra on disk the index has not read (a new folder, or an index of an
  //   older shape): read them, once per page
  if (!scan.running && !rescanned && TARGETS.some((row) => (row.files || 0) < (row.on_disk || 0))) {
    rescanned = true;
    scan();
    return;
  }
  // an instrument from the targets when none was chosen yet
  if (!S.instrument_set) {
    const counts = {};
    TARGETS.forEach((row) => { const g = guessInstrument(row.instrument); if (g) counts[g] = (counts[g] || 0) + row.files; });
    const best = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
    if (best && best[0] !== S.instrument) { S.instrument = best[0]; $('instrument').value = S.instrument; fillSources(); await loadInstrumentThings(); }
  }
  S.ticked = S.ticked.filter((name) => TARGETS.find((row) => row.name === name));
  drawTargets();
  drawPerTarget();
  await loadPoints();
}

async function scan() {
  S.data_dir = $('data_dir').value.trim();
  save();
  setBackdrop();
  const data = await api.post('/api/scan', { data_dir: S.data_dir });
  if (data.error) { $('scan_status').textContent = data.error; return; }
  await loadInstrumentThings();
  if (scanTimer) clearInterval(scanTimer);
  scanTimer = setInterval(loadTargets, 1000);
  loadTargets();
}

const COLUMNS = [
  { key: 'name', label: 'col_target' },
  { key: 'instrument', label: 'col_instrument' },
  { key: 'files', label: 'col_files', num: true },
  { key: 'nights', label: 'col_nights', num: true },
  { key: 'snr', label: 'col_snr', num: true, digits: 0 },
  { key: 'exptime', label: 'col_exptime', num: true, digits: 0 },
  { key: 'berv_min', label: 'col_berv', num: true },
  { key: 'berv_span', label: 'col_span', num: true },
  { key: 'first', label: 'col_dates' },
  { key: 'teff', label: 'col_teff', num: true, digits: 0 },
];

function colourOf(name) {
  const index = S.ticked.indexOf(name);
  if (index < 0) return null;
  return index < HIST_COLOURED ? css(SERIES[index]) : css('--series-other');
}

function drawTargets() {
  const instruments = [...new Set(TARGETS.map((row) => row.instrument))].sort();
  $('instrument_filters').replaceChildren(...instruments.map((name) => el('label', { class: 'check' },
    el('input', {
      type: 'checkbox', checked: !S.hidden_instruments.includes(name),
      onchange: (event) => {
        S.hidden_instruments = event.target.checked ? S.hidden_instruments.filter((n) => n !== name) : [...S.hidden_instruments, name];
        save(); drawTargets();
      },
    }), name)));
  const rows = TARGETS.filter((row) => !S.hidden_instruments.includes(row.instrument));
  const { key, dir } = S.sort;
  rows.sort((a, b) => {
    const va = a[key];
    const vb = b[key];
    if (va === null || va === undefined) return 1;
    if (vb === null || vb === undefined) return -1;
    return (typeof va === 'string' ? va.localeCompare(vb) : va - vb) * dir;
  });
  const head = el('tr', {}, el('th', {}, ''), ...COLUMNS.map((col) => el('th', {
    class: 'sortable', text: t(col.label) + (S.sort.key === col.key ? (S.sort.dir > 0 ? ' ▴' : ' ▾') : ''),
    onclick: () => { S.sort = { key: col.key, dir: S.sort.key === col.key ? -S.sort.dir : 1 }; save(); drawTargets(); },
  })));
  const body = rows.map((row) => {
    const ticked = S.ticked.includes(row.name);
    const colour = colourOf(row.name);
    const reading = row.files < row.on_disk ? ` (${row.on_disk})` : '';
    return el('tr', { class: ticked ? 'ticked' : '', ondblclick: () => toggle(row.name) },
      el('td', {}, el('input', { type: 'checkbox', checked: ticked, onchange: () => toggle(row.name) })),
      el('td', {}, colour ? el('span', { class: 'swatch', style: `background:${colour}` }) : null, row.name),
      el('td', { text: row.instrument }),
      el('td', { class: 'num', text: `${row.files}${reading}` }),
      el('td', { class: 'num', text: row.nights || '' }),
      el('td', { class: 'num', text: fmt(row.snr, 0) }),
      el('td', { class: 'num', text: fmt(row.exptime, 0) }),
      el('td', { class: 'num', text: row.berv_min === null ? '' : `${fmt(row.berv_min)} → ${fmt(row.berv_max)}` }),
      el('td', { class: 'num', text: fmt(row.berv_span) }),
      el('td', { class: 'mono', text: row.first ? `${mjdDate(row.first).slice(0, 7)} → ${mjdDate(row.last).slice(0, 7)}` : '', 'data-tip': row.first ? `${mjdDate(row.first)} → ${mjdDate(row.last)}` : null }),
      el('td', { class: 'num', text: fmt(row.teff, 0) }));
  });
  $('targets_table').replaceChildren(el('thead', {}, head), el('tbody', {}, body));
  $('ticked').textContent = t('ticked', S.ticked.length, TARGETS.length);
  drawTiles();
  const notes = [];
  const mixed = new Set(TARGETS.filter((row) => S.ticked.includes(row.name)).map((row) => row.instrument));
  if (mixed.size > 1) notes.push(t('mixed_instruments'));
  if (S.ticked.length > 1) notes.push(t('joint_note'));
  $('target_notes').textContent = notes.join(' · ');
}

function drawTiles() {
  const ticked = TARGETS.filter((row) => S.ticked.includes(row.name));
  const sum = (rows, key) => rows.reduce((total, row) => total + (row[key] || 0), 0);
  const count = (x) => Number(x).toLocaleString(S.lang === 'fr' ? 'fr-CA' : 'en-CA');
  const span = (rows) => {
    const firsts = rows.map((row) => row.first).filter((x) => x !== null && x !== undefined);
    const lasts = rows.map((row) => row.last).filter((x) => x !== null && x !== undefined);
    return firsts.length ? `${mjdDate(Math.min(...firsts))} → ${mjdDate(Math.max(...lasts))}` : '';
  };
  const bervs = ticked.filter((row) => row.berv_min !== null && row.berv_min !== undefined);
  const lo = bervs.length ? Math.min(...bervs.map((row) => row.berv_min)) : null;
  const hi = bervs.length ? Math.max(...bervs.map((row) => row.berv_max)) : null;
  const instruments = [...new Set(TARGETS.map((row) => row.instrument).filter(Boolean))].sort();
  const tile = (label, value, sub) => el('div', { class: 'tile' },
    el('div', { class: 'label', text: label }),
    el('div', { class: 'value', text: value }),
    el('div', { class: 'sub', text: sub, title: sub }));
  $('tiles').replaceChildren(
    tile(t('tile_targets'), count(TARGETS.length), instruments.join(' · ')),
    tile(t('tile_spectra'), count(sum(TARGETS, 'files')), span(TARGETS)),
    tile(t('tile_ticked'), count(ticked.length), ticked.length ? t('tile_ticked_sub', count(sum(ticked, 'files'))) : t('tile_none')),
    tile(t('tile_berv'), lo === null ? '-' : `${fmt(hi - lo)} km/s`, lo === null ? t('tile_none') : `${fmt(lo)} → ${fmt(hi)} km/s`));
}

function toggle(name) {
  S.ticked = S.ticked.includes(name) ? S.ticked.filter((n) => n !== name) : [...S.ticked, name];
  save();
  drawTargets();
  loadPoints();
  drawPerTarget();
  wrapEdited = false;
  followTicked();
}

// the instrument follows the ticked targets when they are all of one other
//   family than the one chosen (SPIRou spectra run as NIRPS_HE, 2026-10-23)
const family = (name) => String(name || '').toUpperCase().split('_')[0].replace(/[^A-Z0-9]/g, '');
async function followTicked() {
  const found = [...new Set(TARGETS.filter((row) => S.ticked.includes(row.name)).map((row) => guessInstrument(row.instrument)))];
  if (found.length !== 1 || !found[0] || family(found[0]) === family(S.instrument)) return;
  S.instrument = found[0];
  S.instrument_set = true;
  $('instrument').value = S.instrument;
  fillSources();
  save();
  await loadInstrumentThings();
  $('target_notes').textContent = t('instrument_followed', S.instrument);
}

async function loadPoints() {
  if (!S.ticked.length || !S.data_dir) { POINTS = {}; drawPlots(); return; }
  POINTS = await api.get('/api/points', { data_dir: S.data_dir, names: S.ticked.join(',') });
  drawPlots();
}

// ── plots (SVG) ─────────────────────────────────────────────────────────
const NS = 'http://www.w3.org/2000/svg';
function svg(tag, attrs) {
  const node = document.createElementNS(NS, tag);
  Object.entries(attrs || {}).forEach(([k, v]) => { if (v !== null && v !== undefined) node.setAttribute(k, v); });
  return node;
}
function ticks(lo, hi, count) {
  const span = hi - lo || 1;
  const step = 10 ** Math.floor(Math.log10(span / count));
  const nice = [1, 2, 5, 10].map((m) => m * step).find((s) => span / s <= count) || step * 10;
  const out = [];
  for (let v = Math.ceil(lo / nice) * nice; v <= hi + 1e-9; v += nice) out.push(Number(v.toFixed(10)));
  return out;
}
function frame(width, height, margin) {
  const root = svg('svg', { viewBox: `0 0 ${width} ${height}` });
  const inner = { x0: margin.l, x1: width - margin.r, y0: margin.t, y1: height - margin.b };
  return { root, inner };
}
function axes(root, inner, xs, ys, xscale, yscale, xlabel, xfmt) {
  const grid = svg('g', { class: 'grid' });
  ys.forEach((v) => grid.append(svg('line', { x1: inner.x0, x2: inner.x1, y1: yscale(v), y2: yscale(v) })));
  root.append(grid);
  const axis = svg('g', { class: 'axis' });
  axis.append(svg('line', { x1: inner.x0, x2: inner.x1, y1: inner.y1, y2: inner.y1 }));
  xs.forEach((v) => {
    axis.append(svg('line', { x1: xscale(v), x2: xscale(v), y1: inner.y1, y2: inner.y1 + 4 }));
    const label = svg('text', { x: xscale(v), y: inner.y1 + 15, 'text-anchor': 'middle' });
    label.textContent = xfmt ? xfmt(v) : v;
    axis.append(label);
  });
  ys.forEach((v) => {
    const label = svg('text', { x: inner.x0 - 5, y: yscale(v) + 3, 'text-anchor': 'end' });
    label.textContent = v;
    axis.append(label);
  });
  if (xlabel) {
    const label = svg('text', { x: (inner.x0 + inner.x1) / 2, y: inner.y1 + 29, 'text-anchor': 'middle' });
    label.textContent = xlabel;
    axis.append(label);
  }
  root.append(axis);
}
function empty(holder, message) {
  const { root } = frame(360, 80, { l: 0, r: 0, t: 0, b: 0 });
  const text = svg('text', { x: 180, y: 44, 'text-anchor': 'middle', class: 'empty' });
  text.textContent = message || t('no_points');
  root.append(text);
  holder.replaceChildren(root);
}
// a target's colour is its place among the ticked ones, in every plot
function legend(names, coloured) {
  if (names.length < 2) return null;
  const place = (n) => S.ticked.indexOf(n);
  const shown = names.filter((n) => place(n) < coloured);
  const rest = names.length - shown.length;
  const items = shown.map((name) => el('span', {}, el('span', { class: 'swatch', style: `background:${css(SERIES[place(name)])}` }), name));
  if (rest) items.push(el('span', {}, el('span', { class: 'swatch', style: `background:${css('--series-other')}` }), `${t('other_targets')} (${rest})`));
  return el('div', { class: 'legend' }, items);
}
// the bounds are in RJD (BJD - 2400000), as LBL reads them; the headers give MJD, half a day less
function inBounds(mjd) {
  const rjd = mjd + 0.5;
  return (S.min_rjd === null || S.min_rjd === '' || rjd >= S.min_rjd) && (S.max_rjd === null || S.max_rjd === '' || rjd <= S.max_rjd);
}

function drawPlots() {
  const names = S.ticked.filter((name) => POINTS[name] && POINTS[name].berv.length);
  if (!names.length) { empty($('plot_berv')); empty($('plot_vtot')); empty($('plot_snr')); empty($('plot_time')); return; }
  drawHistogram(names);
  drawVtot(names);
  drawScatter(names);
  drawTimeline(names);
}

function drawHistogram(names) {
  histogram($('plot_berv'), names, (n) => POINTS[n].berv.map((v, i) => [v, POINTS[n].mjd[i]]), 'BERV (km/s)', 'BERV');
}

// v_tot = v_sys - BERV: where the star's lines fall against the tellurics,
//   for the targets whose headers give a systemic velocity (the others are
//   left out, not drawn at 0)
function drawVtot(names) {
  const withVsys = names.filter((n) => (POINTS[n].vsys || []).some((v) => v !== null && v !== undefined));
  if (!withVsys.length) { empty($('plot_vtot'), t('no_vsys')); return; }
  histogram($('plot_vtot'), withVsys, (n) => POINTS[n].berv.map((b, i) => {
    const vsys = POINTS[n].vsys[i];
    return vsys === null || vsys === undefined ? null : [vsys - b, POINTS[n].mjd[i]];
  }).filter(Boolean), 'v_tot = v_sys - BERV (km/s)', 'v_tot');
}

// a histogram stacked by target, per 3 km/s; each target keeps its colour
//   (its place among the ticked ones), past the coloured slots one grey
function histogram(holder, names, valuesOf, xlabel, what) {
  const width = 380;
  const height = 190;
  const { root, inner } = frame(width, height, { l: 30, r: 8, t: 6, b: 36 });
  const values = Object.fromEntries(names.map((n) => [n, valuesOf(n)]));
  const all = names.flatMap((n) => values[n].map((pair) => pair[0]));
  const bin = 3;
  const lo = Math.floor(Math.min(...all) / bin) * bin;
  const hi = Math.ceil(Math.max(...all) / bin) * bin + (Math.max(...all) % bin === 0 ? bin : 0);
  const bins = Math.max(1, Math.round((hi - lo) / bin));
  const slot = (n) => Math.min(S.ticked.indexOf(n), HIST_COLOURED);
  const counts = {};
  names.forEach((n) => {
    const s = slot(n);
    counts[s] = counts[s] || new Array(bins).fill(0);
    values[n].forEach(([v, mjd]) => { if (inBounds(mjd)) counts[s][Math.min(bins - 1, Math.floor((v - lo) / bin))] += 1; });
  });
  const slots = Object.keys(counts).map(Number).sort((a, b) => a - b);
  const colourOfSlot = (s) => (s < HIST_COLOURED ? css(SERIES[s]) : css('--series-other'));
  const totals = new Array(bins).fill(0);
  slots.forEach((s) => counts[s].forEach((v, i) => { totals[i] += v; }));
  const top = Math.max(1, ...totals);
  const xscale = (v) => inner.x0 + ((v - lo) / (hi - lo)) * (inner.x1 - inner.x0);
  const yscale = (v) => inner.y1 - (v / top) * (inner.y1 - inner.y0);
  axes(root, inner, ticks(lo, hi, 6), ticks(0, top, 4), xscale, yscale, xlabel);
  const gap = 1;
  for (let i = 0; i < bins; i += 1) {
    let base = 0;
    const x0 = xscale(lo + i * bin) + gap;
    const x1 = xscale(lo + (i + 1) * bin) - gap;
    slots.forEach((s) => {
      const c = counts[s][i];
      if (!c) return;
      root.append(svg('rect', { x: x0, width: Math.max(1, x1 - x0), y: yscale(base + c), height: Math.max(0, yscale(base) - yscale(base + c) - (base ? 1 : 0)), fill: colourOfSlot(s), rx: 1.5 }));
      base += c;
    });
    const lines = names.map((n) => {
      const count = values[n].filter(([v, mjd]) => inBounds(mjd) && Math.min(bins - 1, Math.floor((v - lo) / bin)) === i).length;
      return count ? `${esc(n)}: ${count}` : null;
    }).filter(Boolean);
    const hit = svg('rect', { class: 'hit', x: xscale(lo + i * bin), width: xscale(lo + bin) - xscale(lo), y: inner.y0, height: inner.y1 - inner.y0 });
    hit.dataset.tip = `<span class="mono">${what} ${lo + i * bin} → ${lo + (i + 1) * bin} km/s</span><br>${t('n_spectra', totals[i])}${lines.length > 1 ? `<br>${lines.join('<br>')}` : ''}`;
    root.append(hit);
  }
  holder.replaceChildren(...[legend(names, HIST_COLOURED), root].filter(Boolean));
}

function drawScatter(names) {
  const width = 380;
  const height = 200;
  const { root, inner } = frame(width, height, { l: 36, r: 8, t: 6, b: 36 });
  const xs = [];
  const ys = [];
  names.forEach((n) => POINTS[n].berv.forEach((v, i) => { if (POINTS[n].snr[i] !== null) { xs.push(v); ys.push(POINTS[n].snr[i]); } }));
  if (!xs.length) { empty($('plot_snr')); return; }
  const xlo = Math.min(...xs) - 1;
  const xhi = Math.max(...xs) + 1;
  const yhi = Math.max(...ys) * 1.05;
  const xscale = (v) => inner.x0 + ((v - xlo) / (xhi - xlo)) * (inner.x1 - inner.x0);
  const yscale = (v) => inner.y1 - (v / yhi) * (inner.y1 - inner.y0);
  axes(root, inner, ticks(xlo, xhi, 6), ticks(0, yhi, 4), xscale, yscale, 'BERV (km/s)');
  // grey first, so that the coloured three sit on top
  const order = names.map((n, i) => [n, i]).sort((a, b) => (b[1] >= SCATTER_COLOURED) - (a[1] >= SCATTER_COLOURED));
  order.forEach(([n, s]) => {
    const colour = s < SCATTER_COLOURED ? css(SERIES[s]) : css('--series-other');
    POINTS[n].berv.forEach((v, i) => {
      const snr = POINTS[n].snr[i];
      if (snr === null) return;
      const dot = svg('circle', { cx: xscale(v), cy: yscale(snr), r: 3.6, fill: colour, stroke: css('--surface'), 'stroke-width': 1, opacity: inBounds(POINTS[n].mjd[i]) ? 1 : 0.25 });
      dot.dataset.tip = `${esc(n)}<br><span class="mono">BERV ${fmt(v, 2)} km/s · SNR ${fmt(snr, 0)} · ${mjdDate(POINTS[n].mjd[i])}</span>`;
      root.append(dot);
    });
  });
  $('plot_snr').replaceChildren(...[legend(names, SCATTER_COLOURED), root].filter(Boolean));
}

function drawTimeline(names) {
  const width = 380;
  const rowHeight = 14;
  const height = 40 + rowHeight * names.length;
  const { root, inner } = frame(width, height, { l: 8, r: 8, t: 4, b: 34 });
  const all = names.flatMap((n) => POINTS[n].mjd.filter((m) => m !== null));
  if (!all.length) { empty($('plot_time')); return; }
  const lo = Math.min(...all) - 5;
  const hi = Math.max(...all) + 5;
  const xscale = (v) => inner.x0 + ((v - lo) / (hi - lo)) * (inner.x1 - inner.x0);
  const years = [];
  for (let y = Number(mjdDate(lo).slice(0, 4)); y <= Number(mjdDate(hi).slice(0, 4)) + 1; y += 1) {
    const mjd = (Date.UTC(y, 0, 1) / 86400000) + 40587;
    if (mjd >= lo && mjd <= hi) years.push(mjd);
  }
  const marks = years.length >= 2 ? years : ticks(lo, hi, 4);
  axes(root, inner, marks, [], xscale, () => 0, years.length >= 2 ? '' : 'RJD', (v) => (years.length >= 2 ? mjdDate(v).slice(0, 4) : `${Math.round(v + 0.5)}`));
  if (S.min_rjd !== null && S.min_rjd !== '' && S.min_rjd > lo) root.append(svg('rect', { x: inner.x0, width: xscale(S.min_rjd) - inner.x0, y: inner.y0, height: inner.y1 - inner.y0, fill: 'rgba(255,255,255,0.05)' }));
  if (S.max_rjd !== null && S.max_rjd !== '' && S.max_rjd < hi) root.append(svg('rect', { x: xscale(S.max_rjd), width: inner.x1 - xscale(S.max_rjd), y: inner.y0, height: inner.y1 - inner.y0, fill: 'rgba(255,255,255,0.05)' }));
  names.forEach((n, s) => {
    const colour = s < HIST_COLOURED ? css(SERIES[s]) : css('--series-other');
    const y = inner.y0 + 4 + s * rowHeight;
    POINTS[n].mjd.forEach((m) => {
      if (m === null) return;
      const mark = svg('rect', { x: xscale(m) - 1, width: 2, y, height: rowHeight - 4, fill: colour, opacity: inBounds(m) ? 1 : 0.3 });
      mark.dataset.tip = `${esc(n)}<br><span class="mono">${mjdDate(m)} · RJD ${fmt(m + 0.5, 3)}</span>`;
      root.append(mark);
    });
  });
  $('plot_time').replaceChildren(root);
}

// ── settings ────────────────────────────────────────────────────────────
async function loadInstrumentThings() {
  const data = await api.get('/api/options', { instrument: S.instrument, lang: S.lang });
  OPTIONS = data.options || [];
  SWITCHES = data.switches || [];
  VETTED = await api.get('/api/vetted', { instrument: S.instrument });
  if (!Array.isArray(VETTED)) VETTED = [];
  if (S.data_dir) {
    BASES = await api.get('/api/bases', { data_dir: S.data_dir, instrument: S.instrument, source: S.source });
    TEMPLATES = await api.get('/api/templates', { data_dir: S.data_dir, instrument: S.instrument });
    // a frozen basis of another instrument or source cannot stay chosen
    const basis = S.pca2d.input_name;
    if (basis && !BASES.some((b) => b.compatible && b.name === basis)) {
      delete S.pca2d.input_name;
      save();
      $('target_notes').textContent = t('basis_dropped', basis, S.instrument, S.source);
    }
  }
  drawOptions();
  drawSwitches();
  drawPerTarget();
  drawExtra();
}

const CHOICES = { weight: ['flux', 'velocity'], mask: ['common', 'exposure', 'none'] };

function optionValue(row) {
  return Object.prototype.hasOwnProperty.call(S.pca2d, row.key) ? S.pca2d[row.key] : row.default;
}

function setOption(row, value) {
  const same = value === row.default || (value === '' && (row.default === null || row.default === undefined));
  if (same) delete S.pca2d[row.key];
  else S.pca2d[row.key] = value;
  wrapEdited = false;
  save();
  drawOptions();
}

function control(row) {
  const value = optionValue(row);
  const set = Object.prototype.hasOwnProperty.call(S.pca2d, row.key);
  if (row.key === 'input_name') {
    const select = el('select', { class: set ? 'set' : '', onchange: (event) => setOption(row, event.target.value || null) },
      el('option', { value: '', text: t('basis_none') }),
      // only the bases of this instrument and data source: LBL refuses the others
      ...BASES.filter((b) => b.compatible).map((b) => el('option', {
        value: b.name, text: t('basis_label', b.name, b.n_earth ?? '?', b.objects.length),
      })));
    select.value = value || '';
    return select;
  }
  if (CHOICES[row.key]) {
    const select = el('select', { class: set ? 'set' : '', onchange: (event) => setOption(row, event.target.value) },
      ...CHOICES[row.key].map((c) => el('option', { value: c, text: c })));
    select.value = value ?? '';
    return select;
  }
  if (row.kind === 'bool') {
    return el('input', { type: 'checkbox', checked: Boolean(value), onchange: (event) => setOption(row, event.target.checked) });
  }
  if (row.kind === 'int' || row.kind === 'float') {
    return el('input', {
      type: 'number', step: row.kind === 'int' ? 1 : 'any', class: set ? 'set' : '',
      value: set ? value : '', placeholder: row.default ?? t('unset'),
      onchange: (event) => {
        const raw = event.target.value;
        if (raw === '') { setOption(row, row.default); return; }
        setOption(row, row.kind === 'int' ? parseInt(raw, 10) : parseFloat(raw));
      },
    });
  }
  return el('input', {
    type: 'text', class: set ? 'set' : '', value: set ? (value ?? '') : '', placeholder: row.default ?? defaultName(row.key) ?? t('unset'),
    spellcheck: 'false',
    onchange: (event) => setOption(row, event.target.value.trim() || row.default),
  });
}

// what an unset name will be, said in its grey: the corrected object's
//   (<object>_pca2d) for the variant, the objects' for the basis saved
function defaultName(key) {
  const objects = S.ticked.length ? S.ticked : ['<object>'];
  const more = objects.length > 1 ? ', …' : '';
  if (key === 'name') return `${objects[0]}_pca2d${more}`;
  if (key === 'output_name') return S.pca2d.joint ? objects.join('+') : `${objects[0]}${more}`;
  return null;
}

function drawOptions() {
  const holder = $('options');
  const groups = {};
  OPTIONS.forEach((row) => { (groups[row.group] = groups[row.group] || []).push(row); });
  const parts = [];
  ['model', 'bases', 'correction', 'runs', 'more'].forEach((group) => {
    if (!groups[group]) return;
    parts.push(el('div', { class: 'group-title', text: t(`group_${group}`) }));
    parts.push(el('div', { class: 'options-grid' }, groups[group].map((row) => {
      const set = Object.prototype.hasOwnProperty.call(S.pca2d, row.key);
      // the window's own help; LBL's description (English) for an option it has none for yet
      const help = row.help ? helpHtml(row.help) : (row.lbl ? `${esc(t('lbl_says'))}<br>${helpHtml(row.lbl)}` : '');
      return el('div', { class: `option${set ? ' changed' : ''}` },
        el('div', { class: 'name' }, row.label, help ? el('span', { class: 'info', 'data-tip': help, text: 'i' }) : null,
          el('div', { class: 'key', text: `${row.key} · ${t('default')} ${row.default === null || row.default === undefined ? t('unset') : row.default}` })),
        el('div', { class: 'control' }, control(row)),
        el('button', { type: 'button', class: 'reset', title: t('reset'), text: '↺', onclick: () => { delete S.pca2d[row.key]; save(); drawOptions(); } }));
    })));
  });
  holder.replaceChildren(...parts);
  $('pca2d_on').checked = S.pca2d_on;
  holder.style.opacity = S.pca2d_on ? 1 : 0.4;
}

// NIRPS's and SPIRou's spectra come telluric-corrected (APERO): LBL's own
//   telluric cleaning is off for them, and cannot be ticked
const NO_TELLUCLEAN = ['NIRPS', 'SPIROU'];
function drawSwitches() {
  $('switches').replaceChildren(...SWITCHES.map((row) => {
    let value = Object.prototype.hasOwnProperty.call(S.lbl, row.key) ? S.lbl[row.key] : row.default;
    if (value === null) value = instrumentTelluclean();
    const locked = row.key === 'RUN_LBL_TELLUCLEAN' && NO_TELLUCLEAN.includes(family(S.instrument));
    return el('label', { class: `check${locked ? ' locked' : ''}`, title: locked ? t('tellu_off') : null }, el('input', {
      type: 'checkbox', checked: locked ? false : Boolean(value), disabled: locked,
      onchange: (event) => { S.lbl[row.key] = event.target.checked; wrapEdited = false; save(); },
    }), t(`sw_${row.key}`), info(`help_sw_${row.key}`));
  }));
  $('resproj').checked = Boolean(S.resproj);
}

function drawPerTarget() {
  $('vetted_bar').hidden = !VETTED.length;
  const rows = S.ticked.map((name) => {
    const target = TARGETS.find((row) => row.name === name) || {};
    // every template offered says its temperature: the header's for those
    //   in templates/, the scan's for a ticked target's own
    const temps = {};
    TEMPLATES.forEach((tp) => { if (tp.teff) temps[tp.name] = tp.teff; });
    TARGETS.forEach((row) => { if (row.teff && !temps[row.name]) temps[row.name] = row.teff; });
    const labelled = (n) => `${n} (${temps[n] ? Math.round(temps[n]) : '?'} K)`;
    const others = TEMPLATES.map((tp) => tp.name).filter((n) => !/_pca2d(_|$)/.test(n) && !/_tc$/.test(n) && n !== name);
    const choices = [...new Set([...others, ...S.ticked.filter((n) => n !== name)])]
      .sort((a, b) => (temps[a] || 1e9) - (temps[b] || 1e9));
    const own = S.teff[name] || target.teff || temps[name];
    const select = el('select', { onchange: (event) => { if (event.target.value) S.comparison[name] = event.target.value; else delete S.comparison[name]; wrapEdited = false; save(); } },
      el('option', { value: '', text: own ? `${t('comparison_self')} (${Math.round(own)} K)` : t('comparison_self') }),
      ...choices.map((c) => el('option', { value: c, text: labelled(c) })),
      // LBL's vetted templates of this instrument, with their temperature
      VETTED.length ? el('optgroup', { label: t('vetted_group') },
        VETTED.map((v) => el('option', { value: v.name, text: t('vetted_label', v.object, v.teff, v.nfiles) }))) : null);
    select.value = S.comparison[name] || '';
    const teff = el('input', {
      type: 'number', step: 10, value: S.teff[name] ?? '', placeholder: target.teff ? Math.round(target.teff) : '',
      onchange: (event) => { if (event.target.value === '') delete S.teff[name]; else S.teff[name] = Number(event.target.value); wrapEdited = false; save(); },
    });
    const best = VETTED.length ? el('button', { type: 'button', class: 'button small', text: t('best_match'), onclick: () => bestMatch([name]) }) : null;
    return el('tr', {}, el('td', { text: name }), el('td', {}, el('span', { class: 'row gap' }, select, best)), el('td', {}, teff));
  });
  $('per_target').replaceChildren(
    el('thead', {}, el('tr', {}, el('th', { text: t('col_target') }), el('th', {}, t('comparison'), info('help_comparison')), el('th', {}, t('teff'), info('help_teff')))),
    el('tbody', {}, rows.length ? rows : el('tr', {}, el('td', { colspan: 3, class: 'muted', text: t('no_points') }))));
}

// the vetted template of the nearest Teff, for targets of 2900-4300 K
//   (lbl.core.vetted.best_match); the others are said and left as they are
const VETTED_RANGE = [2900, 4300];
function bestMatch(names) {
  const notes = [];
  names.forEach((name) => {
    const target = TARGETS.find((row) => row.name === name) || {};
    const own = TEMPLATES.find((tp) => tp.name === name) || {};
    const teff = Number(S.teff[name] || target.teff || own.teff);
    if (!teff || teff < VETTED_RANGE[0] || teff > VETTED_RANGE[1] || !VETTED.length) {
      notes.push(t('best_match_none', name, teff ? Math.round(teff) : '?'));
      return;
    }
    const best = VETTED.reduce((a, b) => (Math.abs(b.teff - teff) < Math.abs(a.teff - teff) ? b : a));
    S.comparison[name] = best.name;
  });
  $('vetted_notes').textContent = notes.join(' · ');
  wrapEdited = false;
  save();
  drawPerTarget();
}

function drawExtra() {
  const show = (box, text, values) => {
    const keys = Object.keys(values || {});
    $(box).hidden = keys.length === 0;
    $(text).textContent = keys.map((k) => `${k} = ${JSON.stringify(values[k])}`).join('\n');
  };
  show('extra_box', 'extra', S.extra);
  show('pca2d_extra_box', 'pca2d_extra', S.pca2d_extra);
}

// ── loading a wrap ──────────────────────────────────────────────────────
async function loadWrapList() {
  if (!S.data_dir) return;
  const wraps = await api.get('/api/wraps', { data_dir: S.data_dir });
  if (!Array.isArray(wraps)) return;
  $('wrap_list').replaceChildren(el('option', { value: '', text: t('load_pick') }),
    ...wraps.map((w) => el('option', { value: w.path, text: `${w.name}  \u00B7  ${when(w.mtime)}` })));
}

async function loadWrap() {
  const path = $('wrap_path').value.trim() || $('wrap_list').value;
  if (!path) return;
  const data = await api.post('/api/load_wrap', { path });
  const box = $('load_messages');
  if (data.error) { box.replaceChildren(el('div', { class: 'message error', text: data.error })); return; }
  const loaded = data.state;
  const keep = { lang: S.lang, tab: S.tab, python: S.python, sort: S.sort, hidden_instruments: S.hidden_instruments };
  Object.assign(S, JSON.parse(JSON.stringify(DEFAULTS)), keep, loaded,
    { name: loaded.name || '', name_auto: !loaded.name, instrument_set: true });
  const notes = [t('loaded', data.path), ...(data.notes || [])];
  if (data.skipped && data.skipped.length) notes.push(t('load_skipped', data.skipped.join(', ')));
  box.replaceChildren(el('div', { class: 'message warning' }, el('ul', {}, notes.map((n) => el('li', { text: n })))));
  $('data_dir').value = S.data_dir;
  $('run_name').value = S.name;
  $('min_rjd').value = S.min_rjd ?? '';
  $('max_rjd').value = S.max_rjd ?? '';
  $('skip_pca2d').value = S.skip_pca2d === null || S.skip_pca2d === undefined ? '' : String(S.skip_pca2d);
  fillInstruments();
  save();
  await loadInstrumentThings();
  await loadTargets();
  drawExtra();
  wrapEdited = false;
  await build();
}

// ── run ─────────────────────────────────────────────────────────────────
// the big button: green to run, orange and pulsing while a run goes
function updateLaunch(running) {
  const button = $('queue');
  button.classList.toggle('running', Boolean(running));
  $('launch_label').textContent = running
    ? t('launch_running', [running.stage, running.counter].filter(Boolean).join(' ') || t('state_running'))
    : t('launch');
  button.title = running ? t('launch_more') : '';
}

// ── the steps of a run, ticked off as its log goes ──────────────────────
let plannedSteps = [];
const STEP_ICON = { pending: '○', running: '◐', done: '✓', failed: '✗', stopped: '■' };
function drawSteps(steps, title) {
  const holder = $('steps');
  $('steps_note').textContent = title || t('steps_planned');
  const groups = [];
  (steps || []).forEach((step) => {
    const last = groups[groups.length - 1];
    if (last && last.obj === step.obj) last.steps.push(step);
    else groups.push({ obj: step.obj, steps: [step] });
  });
  holder.replaceChildren(...groups.map((group) => el('div', { class: 'step-group' },
    el('span', { class: 'step-obj mono', text: group.obj }),
    ...group.steps.map((step) => el('span', { class: `step ${step.state || 'pending'}` },
      el('span', { class: 'step-icon', text: STEP_ICON[step.state || 'pending'] }),
      t(`step_${step.kind}`))))));
}

// ── the wrap, with Python's colours ─────────────────────────────────────
// one pass over the text: comments, strings (triple-quoted first), numbers,
//   keywords, constants and calls; everything else as it is. The coloured
//   copy sits under a transparent textarea that keeps the editing
const PY_KEYWORDS = new Set(('and as assert break class continue def del elif else except finally for from global if import in '
  + 'is lambda nonlocal not or pass raise return try while with yield').split(' '));
const PY_CONSTANTS = new Set(['True', 'False', 'None']);
const PY_TOKEN = /(#[^\n]*)|("""[\s\S]*?(?:"""|$)|'''[\s\S]*?(?:'''|$)|"(?:\\.|[^"\\\n])*"?|'(?:\\.|[^'\\\n])*'?)|(\b\d+(?:\.\d*)?(?:[eE][-+]?\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)/g;
function highlightPython(text) {
  let out = '';
  let last = 0;
  let match;
  PY_TOKEN.lastIndex = 0;
  while ((match = PY_TOKEN.exec(text)) !== null) {
    out += esc(text.slice(last, match.index));
    const [token, comment, string, number, word] = match;
    let kind = null;
    if (comment) kind = 'cm';
    else if (string) kind = 'st';
    else if (number) kind = 'nu';
    else if (word && PY_KEYWORDS.has(word)) kind = 'kw';
    else if (word && PY_CONSTANTS.has(word)) kind = 'co';
    else if (word && text[PY_TOKEN.lastIndex] === '(') kind = 'fn';
    out += kind ? `<span class="py-${kind}">${esc(token)}</span>` : esc(token);
    last = PY_TOKEN.lastIndex;
  }
  // a last newline needs a line under it, or the copy stops one line short
  return `${out}${esc(text.slice(last))}\n`;
}
function highlightWrap() {
  $('wrap_hl').innerHTML = highlightPython($('wrap_text').value);
  syncWrapScroll();
}
function syncWrapScroll() {
  const pre = $('wrap_hl').parentElement;
  pre.scrollTop = $('wrap_text').scrollTop;
  pre.scrollLeft = $('wrap_text').scrollLeft;
}
function setWrap(text) {
  $('wrap_text').value = text || '';
  highlightWrap();
}

function buildState() {
  const teff = {};
  S.ticked.forEach((name) => {
    const target = TARGETS.find((row) => row.name === name) || {};
    teff[name] = S.teff[name] ?? (target.teff ? Math.round(target.teff) : null);
  });
  return {
    data_dir: S.data_dir, instrument: S.instrument, source: S.source, python: S.python,
    targets: S.ticked, comparison: S.comparison, teff, lbl: S.lbl,
    pca2d_on: S.pca2d_on, pca2d: S.pca2d, skip_pca2d: S.skip_pca2d,
    extra: S.extra, pca2d_extra: S.pca2d_extra,
    min_rjd: S.min_rjd, max_rjd: S.max_rjd, resproj: S.resproj,
    name: S.name_auto ? '' : S.name,
    lang: S.lang,
    // the instrument each target's headers give, checked against the one chosen
    instruments: Object.fromEntries(S.ticked.map((n) => [n, (TARGETS.find((row) => row.name === n) || {}).instrument || ''])),
  };
}

function showMessages(errors, warnings) {
  const parts = [];
  if (errors && errors.length) parts.push(el('div', { class: 'message error' }, el('strong', { text: t('errors') }), el('ul', {}, errors.map((e) => el('li', { text: e })))));
  if (warnings && warnings.length) parts.push(el('div', { class: 'message warning' }, el('strong', { text: t('warnings') }), el('ul', {}, warnings.map((w) => el('li', { text: w })))));
  $('messages').replaceChildren(...parts);
}

async function build() {
  const data = await api.post('/api/build', buildState());
  if (data.error) { showMessages([data.error], []); return null; }
  if (S.name_auto) { S.name = data.name; $('run_name').value = data.name; }
  setWrap(data.wrap);
  wrapEdited = false;
  plannedSteps = data.steps || [];
  if (!selectedJob) drawSteps(plannedSteps);
  showMessages(data.errors, data.warnings);
  $('queue').disabled = Boolean(data.errors && data.errors.length);
  return data;
}

async function queue() {
  const data = await api.post('/api/queue', { state: buildState(), name: S.name, wrap: $('wrap_text').value });
  if (data.errors) { showMessages(data.errors, []); return; }
  if (data.error) { showMessages([data.error], []); return; }
  selectJob(data.id);
  pollQueue();
}

async function saveWrap(overwrite) {
  const data = await api.post('/api/save_wrap', { data_dir: S.data_dir, name: S.name, wrap: $('wrap_text').value, overwrite });
  if (data.exists && !overwrite) {
    if (await confirmBox(t('overwrite_q', data.path || data.error))) saveWrap(true);
    return;
  }
  $('save_status').textContent = data.path ? t('saved', data.path) : (data.error || '');
}

async function pollQueue() {
  const jobs = await api.get('/api/queue', { data_dir: S.data_dir });
  if (!Array.isArray(jobs)) return;
  const shown = jobs.slice(-12).reverse();
  $('queue_list').replaceChildren(...(shown.length ? shown.map((job) => el('div', {
    class: `job${job.id === selectedJob ? ' selected' : ''}`, onclick: () => selectJob(job.id),
  },
  el('div', { class: 'row spread' }, el('span', { class: 'title', text: job.name }), el('span', { class: `badge ${job.state}`, text: t(`state_${job.state}`) })),
  el('div', { class: 'meta', text: [job.stage, job.counter, job.state === 'running' ? took(job.started) : (job.ended ? took(job.started, job.ended) : '')].filter(Boolean).join(' · ') }),
  job.reports && job.reports.length ? el('div', { class: 'meta' }, job.reports.slice(-3).map((p) => [fileLink(p, p.split('/').pop()), ' '])) : null))
    : [el('p', { class: 'hint small', text: t('queue_empty') })]));
  if (!selectedJob) {
    const running = jobs.find((job) => job.state === 'running') || jobs[jobs.length - 1];
    if (running) selectJob(running.id);
  }
  updateLaunch(jobs.find((j) => j.state === 'running'));
  const job = jobs.find((j) => j.id === selectedJob);
  if (job && job.steps && job.steps.length) drawSteps(job.steps, t('steps_of', job.name));
  else drawSteps(plannedSteps);
  if (job) {
    $('log_stage').textContent = [job.stage, job.counter].filter(Boolean).join(' · ');
    $('log_stage').className = `badge ${job.state}`;
    $('log_status').textContent = job.status || '';
    $('stop').textContent = job.state === 'queued' ? t('cancel') : t('stop');
    $('stop').disabled = !['queued', 'running'].includes(job.state);
  }
}

function selectJob(id) {
  if (selectedJob === id && stream) return;
  selectedJob = id;
  if (stream) stream.close();
  $('log').replaceChildren();
  logLast = null;
  $('log_title').textContent = id;
  stream = new EventSource(`/api/stream?id=${encodeURIComponent(id)}&from=0`);
  const apply = (payload) => {
    const box = $('log');
    // the log follows the run, unless one has scrolled up to read it: back
    //   at the bottom, it follows again
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    payload.events.forEach((event) => {
      if (event.op === 'replace' && logLast) {
        logLast.textContent = event.text;
        logLast.className = `lv-${event.level}`;
      } else {
        // lv-: a line's level; a bare 'info' is the (i) of the helps
        logLast = el('div', { class: `lv-${event.level}`, text: event.text });
        box.append(logLast);
        while (box.childElementCount > LOG_LINES) box.firstElementChild.remove();
      }
    });
    if (atBottom) box.scrollTop = box.scrollHeight;
  };
  stream.onmessage = (message) => apply(JSON.parse(message.data));
  stream.addEventListener('end', (message) => { apply(JSON.parse(message.data)); stream.close(); stream = null; pollQueue(); });
  stream.onerror = () => { /* the browser reconnects on its own */ };
  pollQueue();
}

async function stopJob() {
  if (!selectedJob) return;
  await api.post('/api/stop', { id: selectedJob });
  pollQueue();
}

// ── runs ────────────────────────────────────────────────────────────────
function table(holder, head, rows) {
  holder.replaceChildren(el('thead', {}, el('tr', {}, head.map((h) => el('th', { text: t(h) })))),
    el('tbody', {}, rows.length ? rows : el('tr', {}, el('td', { colspan: head.length, class: 'muted', text: t('nothing') }))));
}

async function loadRuns() {
  if (!S.data_dir) return;
  const data = await api.get('/api/runs', { data_dir: S.data_dir });
  table($('runs_window'), ['col_name', 'col_state', 'col_started', 'col_duration', 'col_reports', 'log'],
    (data.window || []).map((run) => el('tr', {},
      el('td', { class: 'mono', text: run.name }),
      el('td', {}, el('span', { class: `badge ${run.state}`, text: t(`state_${run.state}`) })),
      el('td', { class: 'mono', text: when(run.started || run.created) }),
      el('td', { class: 'mono', text: run.started ? took(run.started, run.ended) : '' }),
      el('td', {}, (run.reports || []).map((p) => [fileLink(p, p.split('/').pop()), ' '])),
      el('td', {}, fileLink(run.log, 'run.log'), ' ', fileLink(run.wrap, 'wrap.py')))));
  table($('runs_pca2d'), ['col_object', 'col_tag', 'col_hash', 'col_started', 'col_basis', 'col_report'],
    (data.pca2d || []).map((run) => el('tr', {},
      el('td', { text: run.object }),
      el('td', { class: 'mono', text: run.tag }),
      el('td', { class: 'mono', text: run.hash || '' }),
      el('td', { class: 'mono', text: (run.started || '').slice(0, 16).replace('T', ' ') }),
      el('td', { class: 'mono', text: run.basis || '' }),
      el('td', {}, run.report ? fileLink(run.report, run.report.split('/').pop()) : ''))));
  table($('runs_reports'), ['col_name', 'col_date', 'col_size'],
    (data.reports || []).map((report) => el('tr', {},
      el('td', {}, fileLink(report.path, report.name)),
      el('td', { class: 'mono', text: when(report.mtime) }),
      el('td', { class: 'num', text: human(report.size) }))));
}

// ── cleanup ─────────────────────────────────────────────────────────────
let CLEANUP = [];
async function measure() {
  if (!S.data_dir) return;
  $('cleanup_status').textContent = t('measuring');
  const data = await api.get('/api/cleanup', { data_dir: S.data_dir });
  CLEANUP = data.items || [];
  const busy = data.busy || [];
  $('cleanup_status').textContent = '';
  $('delete').disabled = busy.length > 0;
  const kinds = ['scratch', 'rebuildable', 'results', 'data'];
  const parts = [];
  kinds.forEach((kind) => {
    const items = CLEANUP.filter((item) => item.kind === kind);
    if (!items.length) return;
    const total = items.reduce((sum, item) => sum + item.bytes, 0);
    parts.push(el('div', { class: 'kind-title' }, t(`kind_${kind}`), el('span', { class: 'size', text: `${t('total')} ${human(total)}` })));
    const deletable = kind === 'scratch' || kind === 'rebuildable';
    parts.push(el('div', { class: 'table-wrap' }, el('table', { class: 'data' },
      el('tbody', {}, items.map((item) => el('tr', {},
        el('td', {}, deletable ? el('input', { type: 'checkbox', 'data-path': item.path }) : ''),
        el('td', { class: 'mono', text: relative(item.path) + (item.link ? ` → ${item.link}` : '') }),
        el('td', { class: 'muted small', text: T[`what_${item.code}`] || item.what }),
        el('td', { class: 'num', text: human(item.bytes) }),
        el('td', { class: 'num', text: item.files })))))));
  });
  if (busy.length) {
    parts.unshift(el('div', { class: 'message warning' }, t('busy', busy.map((p) => `pid ${p.pid}: ${p.command}`).join(' \u00B7 '))));
  }
  $('cleanup').replaceChildren(...parts);
}

async function deleteSelected() {
  const paths = [...document.querySelectorAll('#cleanup input[type=checkbox]:checked')].map((box) => box.dataset.path);
  if (!paths.length) return;
  const total = CLEANUP.filter((item) => paths.includes(item.path)).reduce((sum, item) => sum + item.bytes, 0);
  const list = paths.map((p) => `  ${relative(p)}`).join('\n');
  if (!(await confirmBox(`${t('confirm_delete', paths.length, human(total))}\n\n${list}`))) return;
  const results = await api.post('/api/delete', { data_dir: S.data_dir, paths });
  const done = (Array.isArray(results) ? results : []).filter((r) => r.done).length;
  $('cleanup_status').textContent = t('deleted', done);
  measure();
}

// ── background ──────────────────────────────────────────────────────────
let backdropFor = null;
async function setBackdrop() {
  const wanted = `${S.data_dir}|${S.theme}`;
  if (!S.data_dir || backdropFor === wanted) return;
  backdropFor = wanted;
  const folder = S.data_dir;
  const theme = S.theme;
  for (let i = 0; i < 60 && `${S.data_dir}|${S.theme}` === wanted; i += 1) {
    const status = await api.get('/api/backdrop_status', { data_dir: folder, theme });
    if (status.none) return;
    if (status.ready) {
      const url = `/api/backdrop?data_dir=${encodeURIComponent(folder)}&theme=${theme}&k=${status.key}`;
      const image = new Image();
      image.onload = () => {
        if (`${S.data_dir}|${S.theme}` !== wanted) return;
        $('backdrop').style.backgroundImage = `url("${url}")`;
        $('backdrop').classList.add('ready');
      };
      image.src = url;
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

// ── start ───────────────────────────────────────────────────────────────
async function init() {
  const state = await api.get('/api/state');
  Object.assign(S, JSON.parse(JSON.stringify(DEFAULTS)), state.state || {});
  document.documentElement.dataset.theme = S.theme;
  S.python = S.python || state.python;
  $('version').textContent = state.version;
  $('lbl_home').textContent = state.lbl;
  await loadStrings();
  INSTRUMENTS = await api.get('/api/instruments');
  fillInstruments();
  $('data_dir').value = S.data_dir;
  $('python').value = S.python;
  $('min_rjd').value = S.min_rjd ?? '';
  $('max_rjd').value = S.max_rjd ?? '';
  $('run_name').value = S.name || '';

  $('theme').onclick = switchTheme;
  $('lang').onclick = async () => { S.lang = S.lang === 'fr' ? 'en' : 'fr'; save(); await loadStrings(); await loadInstrumentThings(); drawTargets(); drawPlots(); pollQueue(); if (S.tab === 'runs') loadRuns(); };
  document.querySelectorAll('#tabs button').forEach((b) => { b.onclick = () => showTab(b.dataset.tab); });
  $('scan').onclick = scan;
  $('data_dir').onkeydown = (event) => { if (event.key === 'Enter') scan(); };
  $('instrument').onchange = async (event) => { S.instrument = event.target.value; S.instrument_set = true; fillSources(); save(); await loadInstrumentThings(); wrapEdited = false; };
  $('source').onchange = async (event) => { S.source = event.target.value; save(); await loadInstrumentThings(); wrapEdited = false; };
  $('python').onchange = (event) => { S.python = event.target.value.trim(); save(); };
  $('tick_all').onclick = () => { S.ticked = TARGETS.filter((row) => !S.hidden_instruments.includes(row.instrument)).map((row) => row.name); save(); drawTargets(); loadPoints(); drawPerTarget(); followTicked(); };
  $('tick_none').onclick = () => { S.ticked = []; save(); drawTargets(); loadPoints(); drawPerTarget(); };
  const bound = (key) => (event) => { S[key] = event.target.value === '' ? null : Number(event.target.value); save(); drawPlots(); wrapEdited = false; };
  $('min_rjd').onchange = bound('min_rjd');
  $('max_rjd').onchange = bound('max_rjd');
  $('pca2d_on').onchange = (event) => { S.pca2d_on = event.target.checked; save(); drawOptions(); wrapEdited = false; };
  $('skip_pca2d').onchange = (event) => { S.skip_pca2d = event.target.value === '' ? null : event.target.value === 'true'; save(); wrapEdited = false; };
  $('resproj').onchange = (event) => { S.resproj = event.target.checked; save(); wrapEdited = false; };
  $('run_name').oninput = (event) => { S.name = event.target.value.trim(); S.name_auto = false; save(); };
  $('name_auto').onclick = () => { S.name_auto = true; save(); build(); };
  $('wrap_text').oninput = () => { wrapEdited = true; highlightWrap(); };
  $('wrap_text').onscroll = syncWrapScroll;
  $('check').onclick = build;
  $('load_wrap').onclick = loadWrap;
  $('wrap_list').onchange = (event) => { $('wrap_path').value = event.target.value; };
  $('queue').onclick = queue;
  $('save_wrap').onclick = () => saveWrap(false);
  $('stop').onclick = stopJob;
  $('runs_refresh').onclick = loadRuns;
  $('measure').onclick = measure;
  $('best_all').onclick = () => bestMatch(S.ticked);
  $('delete').onclick = deleteSelected;

  await loadInstrumentThings();
  await loadTargets();
  await followTicked();
  setBackdrop();
  showTab(S.tab || 'targets');
  pollQueue();
  setInterval(pollQueue, 2000);
}

init();
