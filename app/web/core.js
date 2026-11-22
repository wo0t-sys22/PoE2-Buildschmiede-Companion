const runKey = 'poe2-r17-run-v1';
const preferencesKey = 'poe2-r17-preferences-v1';
const snapshotKey = 'poe2-r17-snapshot-v1';
export const RELEASE_VERSION = '0.19.0';
export const RELEASE_LABEL = `v.${RELEASE_VERSION}`;
let language = 'de';
let itemTerms = new Map();
let itemPattern = null;
let itemColors = {};
const regexEscape = text => [...text].map(char => '\\^$.*+?()[]{}|'.includes(char) ? '\\' + char : char).join('');
export const termKey = text => text.toLowerCase().replace(/’/g, "'");

function termPattern(aliases) {
  const terms = [...aliases.keys()].sort((left, right) => right.length - left.length);
  return terms.length ? new RegExp('(?<![\\p{L}\\p{N}_])(?:'
    + terms.map(term => regexEscape(term).replace(/'/g, "['’]")).join('|')
    + ')(?![\\p{L}\\p{N}_])', 'giu') : null;
}

export function termLabels(term, language) {
  return term.templateLabels
    ? Object.values(term.templateLabels).map(labels => labels[language])
    : [term.labels?.[language]].filter(Boolean);
}

export function termRoles(termCatalog, language) {
  const aliases = new Map();
  for (const term of Object.values(termCatalog)) {
    for (const name of term.aliases ?? []) aliases.set(termKey(name), term.role);
  }
  if (language) {
    for (const term of Object.values(termCatalog)) {
      for (const name of [...(term.routeAliases ?? []), ...termLabels(term, language)]) {
        aliases.set(termKey(name), term.role);
      }
    }
  }
  return aliases;
}

function loadItemTerms(guide, termCatalog) {
  itemColors = guide.palette;
  itemTerms = termRoles(termCatalog);
  itemPattern = termPattern(itemTerms);
}

export function coloredText(value, aliases, palette, role, pattern = termPattern(aliases)) {
  const text = String(value ?? '');
  const color = (label, kind) => /^[a-z_]+$/.test(kind || '') && /^#[a-f0-9]{6}$/i.test(palette[kind] || '')
    ? '<span class="poe-item poe-' + kind + '" style="color:' + palette[kind] + '">' + esc(label) + '</span>'
    : esc(label);
  if (role) return color(text, role);
  if (!pattern) return esc(text);
  let markup = '';
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    markup += esc(text.slice(last, match.index)) + color(match[0], aliases.get(termKey(match[0])));
    last = match.index + match[0].length;
  }
  return markup + esc(text.slice(last));
}

export function itemText(value, role) {
  return coloredText(value, itemTerms, itemColors, role, itemPattern);
}

export const languages = ['de', 'en', 'hybrid'];
export const views = ['transfer', 'home', 'campaign', 'builds', 'atlas', 'respec', 'overview', 'live'];

export function setLanguage(value) {
  language = languages.includes(value) ? value : 'de';
  document.documentElement.lang = language === 'en' ? 'en' : 'de';
}

export function locale() {
  return language;
}

export function tr(de, en, hybrid = de) {
  return language === 'en' ? en : language === 'hybrid' ? hybrid : de;
}

export function esc(value = '') {
  return String(value ?? '').replace(/[&<>"']/g, part => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[part]);
}

const symbols = {
  home: '<path d="m3 10 9-7 9 7v10H3zM9 20v-6h6v6"/>',
  settings: '<path d="M4 6h16M4 12h16M4 18h16"/><path d="M8 4v4m8 2v4m-5 2v4"/>',
  classes: '<path d="M3 7c2 0 3-1 3-3h12c0 2 1 3 3 3v8c-1 3-5 5-9 6-4-1-8-3-9-6z"/><path d="M12 7v10m-4-6h8"/>',
  overview: '<rect x="3.5" y="3.5" width="7" height="7" rx="1"/><rect x="13.5" y="3.5" width="7" height="7" rx="1"/><rect x="3.5" y="13.5" width="7" height="7" rx="1"/><rect x="13.5" y="13.5" width="7" height="7" rx="1"/>',
  respec: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 11h2m4 0h2M8 15h2m4 0h2M8 18h2m4 0h2"/>',
  campaign: '<path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3zM9 3v15m6-12v15"/>',
  builds: '<path d="m3 3 5 1 11 11-4 4L4 8zM14 16l3 3m-3-1-3 3m7-7 3-3M21 3l-5 1-4.5 4.5M9 14l-4 4m-1-2 5 5m10-18 2 2"/>',
  atlas: '<circle cx="12" cy="12" r="8.5"/><path d="m15.5 8.5-2 5-5 2 2-5 5-2ZM12 2v3m0 14v3M2 12h3m14 0h3"/>',
  live: '<path d="M2.5 12h4l3-6 4 13 3-7h5"/>',
  overlay: '<rect x="3" y="4.5" width="18" height="13" rx="2"/><path d="M8 21h8m-4-3.5V21m2-13h4m0 0v4m0-4-4 4"/>',
  arrow: '<path d="M4 12h15m-5-5 5 5-5 5"/>',
  prev: '<path d="m14.5 6-6 6 6 6"/>',
  next: '<path d="m9.5 6 6 6-6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  pin: '<path d="M18.5 10c0 4.5-6.5 10-6.5 10s-6.5-5.5-6.5-10a6.5 6.5 0 0 1 13 0Z"/><circle cx="12" cy="10" r="2"/>',
  level: '<path d="m4 14 8-8 8 8M7.5 17.5 12 13l4.5 4.5"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/>',
  skull: '<path d="M8 17v3h8v-3a7 7 0 1 0-8 0Zm4 0v3"/><circle cx="9" cy="12" r="0.9"/><circle cx="15" cy="12" r="0.9"/>',
  shield: '<path d="M12 21s7-3.5 7-9V6l-7-3-7 3v6c0 5.5 7 9 7 9Z"/><path d="m9 12 2 2 4-4"/>',
  gem: '<path d="M8 4h8l4 6-8 10-8-10zM4 10h16m-12-6 4 16 4-16"/>',
  search: '<circle cx="10.5" cy="10.5" r="5.5"/><path d="m15 15 4.5 4.5"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  file: '<path d="M6 3.5h8l4 4v13H6zM14 3.5v5h4M9 13h6m-6 3h6"/>',
  terminal: '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="m7 9 3 3-3 3m6 0h4"/>',
  link: '<path d="M13 5h6v6m0-6-8 8M10 5H5v14h14v-5"/>',
  flag: '<path d="M5 21V4m0 1 5-1 5 2 4-1v9l-4 1-5-2-5 1"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M5 16v4h14v-4"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/>',
  wind: '<path d="M3 8h13a2.5 2.5 0 1 0-2.5-2.5M3 12h17m-17 4h10a2.5 2.5 0 1 1-2.5 2.5"/>',
  spark: '<path d="m12 2 2.2 7.8L22 12l-7.8 2.2L12 22l-2.2-7.8L2 12l7.8-2.2L12 2Z"/>',
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.8"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><ellipse cx="12" cy="12" rx="3.5" ry="8.5"/><path d="M4 12h16"/>',
};

export const icon = (name, className = '') =>
  `<svg class="icon ${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.55" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${symbols[name] ?? ''}</svg>`;

export const badge = (text, tone = 'neutral') =>
  `<span class="badge badge--${tone}">${esc(text)}</span>`;

export function viewLabel(view) {
  return ({
    transfer: tr('Website-Transfer', 'Website transfer'),
    home: tr('Start', 'Home'), overview: tr('Run-Übersicht', 'Run overview'), campaign: tr('Kampagne', 'Campaign'),
    builds: 'Builds', atlas: 'Endgame & Atlas', live: tr('Live-Daten', 'Live data'),
    respec: tr('Respec-Rechner', 'Respec Calculator', 'Respec Calculator'),
  })[view];
}

export const unknown = () => tr('Unbekannt', 'Unknown');
export const reference = () => tr('0.5.5f · Referenz', '0.5.5f · Reference');

export function stateLabel(run) {
  const labels = {
    offline: [tr('Getrennt', 'Disconnected'), 'neutral'],
    manual: [tr('Manuell', 'Manual'), 'gold'],
    snapshot: [tr('JSON-Snapshot', 'JSON snapshot'), 'gold'],
    log_snapshot: [tr('Letzter Log-Eintrag', 'Last log entry'), 'gold'],
    log_waiting: [tr('Wartet auf Gebiet', 'Waiting for area'), 'gold'],
    log_watching: [tr('Dateiüberwachung', 'File watching'), 'green'],
    native: [tr(`${RELEASE_LABEL} verbunden`, `${RELEASE_LABEL} connected`), 'green'],
    bridge: [tr('R17 verbunden', 'R17 connected'), 'green'],
    stale: [tr('Quelle getrennt', 'Source disconnected'), 'rust'],
  };
  return labels[run.source] ?? labels.offline;
}

export function read(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
  catch { return fallback; }
}

export function write(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; }
  catch { return false; }
}

export const defaults = {
  language: 'de', mode: 'basis', build: 'tactician-supporting-fire',
  act: 'Act 1', zone: 'The Riverbank', following: true, checks: {}, port: 8765,
};

export function loadPreferences() {
  const doc = read(preferencesKey, {});
  const preferences = { ...defaults, ...(record(doc) ? doc : {}) };
  preferences.language = languages.includes(preferences.language) ? preferences.language : 'de';
  preferences.mode = preferences.mode === 'veteran' ? 'veteran' : 'basis';
  preferences.port = portNumber(preferences.port) ?? 8765;
  preferences.checks = record(preferences.checks) ? preferences.checks : {};
  return preferences;
}

export const savePreferences = preferences => write(preferencesKey, preferences);
export const loadSnapshot = () => read(snapshotKey, null);
export const saveSnapshot = state => write(snapshotKey, state);

export const emptyRun = {
  source: 'offline', zone: null, level: null, xp: null, seconds: null,
  startedAt: null, live: false, deaths: null, mode: null, next: null,
  at: null, logTime: null, atlasKind: null, locationStatus: null, logName: null, phase: null, mapTier: null, character: null,
};

export function loadRun({ restoreSources = false } = {}) {
  const data = read(runKey, {});
  const run = { ...emptyRun, ...(record(data) ? data : {}) };
  if (restoreSources && ['native', 'bridge', 'log_watching', 'log_waiting'].includes(run.source)) {
    run.source = 'stale';
    if (run.live && finite(run.seconds, 0) !== null && finite(run.startedAt, 1) !== null) {
      run.seconds = elapsed(run);
      run.live = false;
      run.startedAt = null;
    }
  }
  return run;
}
export const saveRun = run => write(runKey, run);

export function record(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

export function boundedText(value, limit = 300) {
  return typeof value === 'string' ? value.trim().slice(0, limit) || null : null;
}

export function finite(value, min, max = Number.MAX_SAFE_INTEGER) {
  if (typeof value !== 'number' && typeof value !== 'string') return null;
  if (typeof value === 'string' && !value.trim()) return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= min && n <= max ? n : null;
}

export function portNumber(value) {
  const port = finite(value, 1, 65535);
  return Number.isInteger(port) ? port : null;
}

export function zoneKey(value) {
  return String(value ?? '').trim().toLowerCase().replace(/[’‘]/g, "'").replace(/^the\s+/, '');
}

export function hasArea(value) {
  return !!value && !/^(act|akt|interlude|zwischenspiel|t\d+)\b/i.test(value)
    && !['(null)', '(unknown)', 'atlas', '—', 'unbekannt', 'unknown'].includes(zoneKey(value));
}

export function normalizeRun(state, location, timer, source = 'snapshot') {
  if (!record(state) || !record(state.progress) || !record(state.meta)) throw new Error('schema');
  const { progress, meta } = state;
  const provenArea = location?.enabled !== false ? boundedText(location?.zone) : null;
  const mode = boundedText(meta.mode, 70);
  const candidate = boundedText(progress.currentAct);
  const connected = source === 'bridge' || source === 'native';
  const storedSeconds = finite(source === 'native' && timer?.status !== 'live'
    ? progress.runSeconds : timer?.runSeconds ?? progress.runSeconds, 0);
  const startedAt = finite(timer?.runStartedAt ?? meta.runStartedAt, 1);
  const timerLive = (timer?.status ?? meta.status) === 'live' && startedAt !== null;
  const next = boundedText(progress.nextAction, 500);
  const detectedLevel = source === 'native' ? finite(state.levelCheck?.characterLevel, 1, 100) : null;
  const untouched = meta.status === 'prep' && !meta.lastSaved && !meta.character
    && !meta.runStartedAt && Number(progress.level) === 1
    && Number(progress.xpPercent) === 0 && Number(progress.deaths) === 0
    && storedSeconds === 0 && (!next || next === 'Route und Build vorbereiten');
  return {
    ...emptyRun, source, zone: provenArea && hasArea(provenArea) ? provenArea : hasArea(candidate) ? candidate : null,
    level: detectedLevel ?? (untouched ? null : finite(progress.level, 1, 100)),
    xp: untouched ? null : finite(progress.xpPercent, 0, 100),
    deaths: untouched ? null : finite(progress.deaths, 0, 100_000),
    seconds: untouched ? null : storedSeconds === null ? null : storedSeconds
      + (source === 'snapshot' && timerLive ? Math.max(0, Date.now() / 1000 - startedAt) : 0),
    live: connected && timerLive && !untouched,
    startedAt: connected && timerLive ? startedAt : null,
    mode: untouched ? null : mode, character: boundedText(meta.character, 80),
    next: next === 'Route und Build vorbereiten' ? null : next,
    at: Date.now(), logTime: boundedText(location?.last_log_time),
    atlasKind: boundedText(location?.atlasLocation?.kind ?? state.atlasLocation?.kind),
    locationStatus: boundedText(location?.status),
    phase: untouched ? null : boundedText(meta.phase, 50),
    mapTier: finite(progress.mapTier, 1, 100),
  };
}

export function elapsed(run, now = Date.now()) {
  if (run.seconds === null) return null;
  if (!run.live || run.startedAt === null) return Math.floor(run.seconds);
  return Math.floor(run.seconds + Math.max(0, now / 1000 - run.startedAt));
}

export function timeLabel(seconds) {
  if (seconds === null) return '—';
  return [Math.floor(seconds / 3600), Math.floor(seconds % 3600 / 60), seconds % 60]
    .map(part => String(part).padStart(2, '0')).join(':');
}

export function phaseLabel(run, campaignArea) {
  if (run.atlasKind || ['early-maps', 'endgame'].includes(run.phase)) return 'Endgame & Atlas';
  if (campaignArea || run.phase === 'campaign') return tr('Kampagne', 'Campaign');
  return null;
}

export function hcSsf(run) {
  if (!run.mode) return unknown();
  if (/^(hc[\s-]*ssf|ssf[\s-]*hc|hardcore solo self[ -]?found|solo self[ -]?found hardcore)$/i.test(run.mode)) {
    return tr('Aktiv', 'Active');
  }
  return /^(ssf|hc|sc|trade|hc trade|sc trade|hardcore|softcore|solo self[ -]?found|softcore ssf)$/i.test(run.mode)
    ? tr('Inaktiv', 'Inactive') : unknown();
}

export function logHealth(status) {
  return ({
    searching: tr('Suche nach Client.txt', 'Looking for Client.txt'),
    not_found: tr('Client.txt fehlt', 'Client.txt not found'),
    manual_missing: tr('Client.txt fehlt am gewählten Pfad', 'Client.txt missing at selected path'),
    read_error: tr('Client.txt nicht lesbar', 'Cannot read Client.txt'),
    disabled: tr('Erkennung ausgeschaltet', 'Detection disabled'),
    waiting: tr('Wartet auf einen Gebietswechsel', 'Waiting for an area change'),
    last_log_entry: tr('Letzter Log-Eintrag', 'Last log entry'),
    detected: tr('Gebietswechsel erkannt', 'Area change detected'),
  })[status] ?? unknown();
}

export async function assetJson(filename) {
  const response = await fetch(new URL(filename, document.baseURI));
  if (!response.ok) throw new Error(filename);
  return response.json();
}

export async function loadGuide() {
  const [companion, atlas, arenas, tiers, bossLanguages, termData, sectionStyle, respec, tips, guide, catalog] = await Promise.all([
    assetJson('poe2_campaign_companion.json'),
    assetJson('poe2_endgame_atlas.json'), assetJson('poe2_boss_arenas.json'),
    assetJson('poe2_r18_tiers.json'), assetJson('poe2_boss_languages.json'), assetJson('terms.json'),
    assetJson('companion-section-style.json'), assetJson('poe2_respec.json'),
    assetJson('poe2_campaign_tips.json'), assetJson('poe2_r18_guide.json'), assetJson('poe2_language_pilot.json'),
  ]);
  loadItemTerms(guide, termData.terms);
  return { tips, companion, atlas, arenas, guide, tiers, catalog, bossLanguages, sectionStyle, respec,
    termCatalog: termData.terms };
}

export function externalUrl(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}

export function sourceLinks(ids, sources) {
  const links = [...new Set(ids ?? [])].map(id => sources?.[id]).filter(Boolean)
    .map(source => {
      const url = externalUrl(source.url);
      return url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(source.label)}${icon('link')}</a>` : '';
    }).filter(Boolean);
  return links.length ? `<div class="source-links">${links.join('')}</div>` : '';
}

export const list = (items, className = '') => items?.length
  ? `<ul class="points ${className}">${items.map(item => `<li>${itemText(item)}</li>`).join('')}</ul>`
  : `<p class="muted">${unknown()}</p>`;

export function expand(title, content, open = false, role) {
  return `<details class="expand"${open ? ' open' : ''}><summary><span>${itemText(title, role)}</span>${icon('down')}</summary><div class="expand-content">${content}</div></details>`;
}
