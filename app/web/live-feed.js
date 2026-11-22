import { boundedText, record, emptyRun, zoneKey, normalizeRun, portNumber } from './core.js';
import { hubKind } from './r18-panels.js';

const tailSize = 256 * 1024;

export function logIndex(data) {
  const aliases = data.tips.clues.flatMap(clue => [clue.zone, ...(clue.zoneMatch ?? [])]);
  const bossZones = data.companion.bosses.flatMap(boss => [boss.zone, ...(boss.aliases ?? [])]);
  const arenas = new Map(data.arenas.arenas.flatMap(arena => arena.areas.map(area => [zoneKey(area), arena.phase])));
  const campaign = new Set([...aliases.map(zoneKey), ...[...arenas].filter(([, phase]) => phase === 'campaign').map(([key]) => key)]);
  return {
    guide: data.guide,
    known: new Set([...campaign, ...bossZones.map(zoneKey)]),
    maps: new Set(data.atlas.map_scene_names.map(zoneKey).filter(key => !campaign.has(key))),
    arenas,
  };
}

// Patterns and Waystone classification follow R17's server.py.
export function readLog(text, index, pending = null, previous = null) {
  let event = null;
  for (const line of text.split(/\r?\n/)) {
    const generated = line.match(/\bGenerating level (\d+) area "([^"]+)"/);
    if (generated) {
      pending = { level: Number(generated[1]), id: generated[2] };
      continue;
    }
    if (line.includes('[ENGINE] Loading state active: FALSE')) {
      pending = null;
      continue;
    }
    const entered = line.match(/(?:^|\]\s+(?::\s*)?)You have entered (.+)$/);
    const scene = line.match(/(?:^|\]\s+)\[SCENE\] Set Source \[([^\]]+)\]\s*$/);
    const zone = boundedText(entered ? entered[1].replace(/\.\s*$/, '') : scene?.[1]);
    if (!zone) continue;
    const key = zoneKey(zone);
    const hub = hubKind(index.guide, zone);
    if (!entered && (['(null)', '(unknown)', 'atlas'].includes(key) ||
      (!pending && !hub && !index.known.has(key) && !index.maps.has(key) && !index.arenas.has(key)))) continue;
    const same = zoneKey(previous?.zone) === key;
    const endgame = index.arenas.get(key) === 'endgame'
      || (pending ? pending.level >= 65 && (/^map(?!hideout)[a-z0-9_]{2,}$/i.test(pending.id) || index.maps.has(key))
        : same ? previous.kind === 'map' : index.maps.has(key));
    event = { zone, logTime: line.match(/^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}:\d{2}/)?.[0] ?? null,
      kind: hub === 'ziggurat' ? 'hub' : endgame && !hub ? 'map' : null };
    previous = event;
    pending = null;
  }
  return { event, pending };
}

export class LogReader {
  constructor(index) {
    this.index = index;
    this.reset();
  }

  reset() {
    this.offset = null;
    this.modified = null;
    this.partial = '';
    this.pending = null;
    this.event = null;
    this.initial = true;
  }

  async update(file, snapshot = false) {
    if (file.size === this.offset && file.lastModified === this.modified) return undefined;
    const fresh = this.offset === null || file.size <= this.offset || file.size - this.offset > tailSize;
    const start = fresh ? Math.max(0, file.size - tailSize) : this.offset;
    let text = await file.slice(start).text();
    if (fresh && start > 0) text = text.slice(text.indexOf('\n') + 1);
    if (fresh) this.reset();
    const merged = this.partial + text;
    const newline = merged.lastIndexOf('\n');
    const complete = snapshot ? merged : newline >= 0 ? merged.slice(0, newline + 1) : '';
    this.partial = snapshot ? '' : merged.slice(newline + 1).slice(-tailSize);
    const parsed = readLog(complete, this.index, this.pending, this.event);
    this.pending = parsed.pending;
    this.event = parsed.event ?? this.event;
    this.modified = file.lastModified;
    this.offset = file.size;
    this.initial = fresh;
    return fresh || parsed.event ? this.event : undefined;
  }
}

export function areaRun(previous, event, watched, name, initial = false) {
  const retain = ['manual', 'snapshot', 'log_snapshot', 'log_watching', 'log_waiting'].includes(previous.source);
  return {
    ...(retain ? previous : emptyRun),
    zone: event?.zone ?? null, atlasKind: event?.kind ?? null, logTime: event?.logTime ?? null,
    next: null, logName: name, locationStatus: event ? watched && !initial ? 'detected' : 'last_log_entry' : 'waiting',
    source: watched ? event ? 'log_watching' : 'log_waiting' : 'log_snapshot', at: Date.now(),
    phase: null, mapTier: null,
  };
}

export async function nativeAvailable() {
  if (!['127.0.0.1', 'localhost'].includes(location.hostname)) return false;
  try {
    const response = await fetch('./api/build', { cache: 'no-store', signal: AbortSignal.timeout(1800) });
    return response.ok && (await response.json()).build >= 18;
  } catch { return false; }
}

export async function nativeSession() {
  const response = await fetch('./api/session', { cache: 'no-store', signal: AbortSignal.timeout(4000) });
  if (!response.ok) throw new Error('session');
  const payload = await response.json();
  return { ...payload, run: normalizeRun(payload.state, payload.location, payload.timer, 'native') };
}

export async function nativePost(path, payload) {
  const response = await fetch('./api/' + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload), signal: AbortSignal.timeout(4000),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'request');
  return result;
}

export async function bridgeAvailable() {
  if (!['127.0.0.1', 'localhost'].includes(location.hostname)) return false;
  try {
    const response = await fetch('./r17-bridge.json', { cache: 'no-store', signal: AbortSignal.timeout(1800) });
    return response.ok && (await response.json()).bridge === 'r17-read';
  } catch { return false; }
}

export async function bridgeRun(port) {
  if (portNumber(port) === null) throw new Error('port');
  const response = await fetch(`./r17-api?port=${port}`, { cache: 'no-store', signal: AbortSignal.timeout(4000) });
  if (!response.ok) throw new Error('bridge');
  const payload = await response.json();
  const run = normalizeRun(payload.state, payload.location, payload.timer, 'bridge');
  return { run, state: payload.state };
}

export function exportState(base, run, prefs) {
  const data = record(base) ? base : {};
  return {
    ...data,
    guideMode: prefs.mode,
    guideBuild: prefs.build,
    meta: {
      ...data.meta, character: run.character ?? '', mode: run.mode, phase: run.phase ?? data.meta?.phase,
      status: 'prep', runStartedAt: null,
    },
    progress: {
      ...data.progress,
      currentAct: run.zone ?? '',
      nextAction: run.next ?? '',
      level: run.level, xpPercent: run.xp, deaths: run.deaths, runSeconds: run.seconds,
      mapTier: run.mapTier,
    },
  };
}
