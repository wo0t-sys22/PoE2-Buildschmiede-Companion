import {
  tr, esc, badge, icon, setLanguage, stateLabel, elapsed, timeLabel, loadRun,
  loadPreferences, hcSsf, phaseLabel, unknown, loadGuide, portNumber, emptyRun, itemText, RELEASE_LABEL,
} from './core.js';
import { indexGuide, lookupArea, actionForRun } from './guide.js';
import { bridgeAvailable, bridgeRun, nativeAvailable, nativeSession } from './live-feed.js';

const root = document.querySelector('#overlay');
const params = new URLSearchParams(location.search);
const isObs = params.get('obs') === '1';
const port = portNumber(params.get('port'));
let run = loadRun();
let prefs = loadPreferences();
let index = null;
let linked = false;
let native = false;
let lastMarkup = '';

document.documentElement.classList.toggle('obs', isObs);
setLanguage(params.get('lang') ?? prefs.language);

function value(label, data, symbol) {
  return `<div class="hud-metric"><span>${icon(symbol)}${esc(label)}</span><strong>${esc(data == null ? unknown() : data)}</strong></div>`;
}

function render() {
  const [status, tone] = stateLabel(run);
  const area = index && lookupArea(index, run.zone, prefs.act);
  const next = run.next || (index ? actionForRun(data, index, run, prefs) : null);
  const phase = phaseLabel(run, area);
  const seconds = elapsed(run);
  const body = `<section class="hud" aria-label="Race Overlay">
    <header class="hud-top"><div class="eyebrow">${icon('pin')}${tr('Aktuelles Gebiet', 'Current area')}</div>${badge(status, tone)}</header>
    <h1>${esc(run.zone || unknown())}</h1>
    <div class="hud-metrics">
      ${value('Level', run.level, 'level')}
      ${value('XP', run.xp === null ? null : new Intl.NumberFormat(tr('de-DE', 'en-GB'), { maximumFractionDigits: 2 }).format(run.xp) + ' %', 'spark')}
      ${value(tr('Zeit', 'Time'), seconds === null ? null : timeLabel(seconds), 'clock')}
      ${value(tr('Tode', 'Deaths'), run.deaths, 'skull')}
    </div>
    <div class="hud-mode">${icon('shield')}<span>${tr('Spielmodus', 'Game mode')} <b>${esc([phase, run.mode].filter(Boolean).join(' · ') || unknown())}</b></span><span>HC SSF <b>${esc(hcSsf(run))}</b></span></div>
    <div class="hud-next"><span class="eyebrow">${icon('flag')}${tr('Nächste Aktion', 'Next action')}</span><strong>${itemText(next || unknown())}</strong></div>
  </section>`;
  const outer = isObs ? body : `<header class="preview-head">${badge(`${RELEASE_LABEL} · Overlay`, 'gold')}</header>${body}`;
  if (outer !== lastMarkup) {
    root.innerHTML = outer;
    lastMarkup = outer;
  }
}

async function poll() {
  try {
    const latest = native ? await nativeSession() : await bridgeRun(port);
    if (latest.checklist) prefs.checks = latest.checklist.checked;
    run = latest.run;
    if (Array.isArray(latest.state.routeClues) && data) index = indexGuide(data, latest.state.routeClues);
    linked = true;
  } catch {
    const previous = run;
    run = { ...(linked ? previous : emptyRun), seconds: linked ? elapsed(previous) : null, live: false, source: 'stale' };
  }
  render();
  setTimeout(poll, 2000);
}

let data;
async function start() {
  render();
  try {
    data = await loadGuide();
    index = indexGuide(data);
  } catch {}
  native = await nativeAvailable();
  if (native || port && await bridgeAvailable()) void poll();
  else {
    window.addEventListener('storage', () => {
      prefs = loadPreferences();
      run = loadRun();
      if (!params.has('lang')) setLanguage(prefs.language);
      render();
    });
  }
  render();
}

setInterval(render, 250);
void start();
