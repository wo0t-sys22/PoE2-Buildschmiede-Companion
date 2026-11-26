import { tr, zoneKey } from './core.js';
import { cueEnglish } from './translations.js';

export const acts = ['Act 1', 'Act 2', 'Act 3', 'Act 4', 'Act 5', 'Act 6'];
const layoutKinds = new Set(['Wegsignal', 'Layoutregel', 'Gebietseingang', 'Hörhinweis', 'Abstecher für Spirit']);
const bossKinds = new Set(['Boss-Check', 'Optionaler Boss']);
const includeClue = clue => !['blind', 'skip'].includes(clue.status);

export function clueTitle(clue) {
  return tr(clue.cue, cueEnglish[clue.id] || clue.cue);
}

export function indexGuide(data, customClues = []) {
  const areas = new Map(acts.map(act => [act, new Map()]));
  const find = (act, zone, aliases = []) => {
    if (!areas.has(act)) return null;
    const name = String(zone ?? '').trim();
    const key = zoneKey(name);
    if (!key) return null;
    const byAct = areas.get(act);
    if (!byAct.has(key)) byAct.set(key, { key, name, act, aliases: new Set(), clues: [], bosses: [] });
    const area = byAct.get(key);
    aliases.map(zoneKey).filter(Boolean).forEach(alias => area.aliases.add(alias));
    return area;
  };
  const custom = new Map(customClues.filter(clue => typeof clue?.id === 'string').map(clue => [clue.id, clue]));
  const merged = data.tips.clues.map(clue => custom.get(clue.id) || clue);
  const builtIn = new Set(data.tips.clues.map(clue => clue.id));
  merged.push(...[...custom.values()].filter(clue => !builtIn.has(clue.id)));
  const valid = merged.filter(clue => typeof clue.act === 'string' && typeof clue.zone === 'string'
    && typeof clue.cue === 'string' && includeClue(clue));

  for (const clue of valid) {
    for (const zone of clue.zone.split(' / ')) {
      const aliases = clue.zone.includes(' / ') ? [] : (Array.isArray(clue.zoneMatch) ? clue.zoneMatch : []);
      const area = find(clue.act, zone, aliases);
      area?.clues.push(clue);
    }
  }
  for (const boss of data.companion.bosses) {
    const act = boss.act;
    const key = zoneKey(boss.zone);
    const area = [...(areas.get(act)?.values() ?? [])]
      .find(candidate => candidate.key === key || candidate.aliases.has(key))
      ?? find(act, boss.zone);
    area?.bosses.push(boss);
    for (const alias of boss.aliases ?? []) area?.aliases.add(zoneKey(alias));
  }
  for (const [id, name] of Object.entries(data.tips.clientAreaIds ?? {})) {
    const match = /^G([1-4])_/.exec(id);
    if (!match) continue;
    const area = find('Act ' + match[1], name);
    area.clientId ??= id;
  }
  for (const arena of data.arenas.arenas.filter(item => item.phase === 'campaign')) {
    const area = [...areas.values()].flatMap(byAct => [...byAct.values()])
      .find(candidate => candidate.bosses.some(boss => boss.id === arena.id));
    if (area) arena.areas.map(zoneKey).forEach(key => area.aliases.add(key));
  }
  for (const shared of Object.values(data.catalog?.sharedAreas||{})) {
    for (const zone of shared.zones) find(shared.act, zone, shared.aliases?.[zone] || []);
  }
  return new Map([...areas].map(([act, zones]) => [act, [...zones.values()]]));
}

export function overlayContent(data, area) {
  if (!area) return null;
  const key = area.key;
  const shared=data.catalog.sharedZones?.[key];
  if (shared && data.catalog.areaLayouts[shared]) return {id:shared,act:area.act,zone:area.name,content:data.catalog.areaLayouts[shared]};
  const clue = data.tips.clues.filter(includeClue).filter(row => {
    const aliases = (row.zoneMatch ?? [row.zone]).map(zoneKey);
    return row.exactZone ? aliases.includes(key) : aliases.some(alias => alias && key.includes(alias));
  }).sort((a, b) => Number(Boolean(b.mandatory)) - Number(Boolean(a.mandatory)))
    .find(row => data.catalog.areaLayouts[row.id]);
  if (!clue) return null;
  return { id: clue.id, act: clue.act, zone: clue.zone, content: data.catalog.areaLayouts[clue.id] };
}

export const sectionLanguages = ['de', 'hybrid', 'en'];

export function campaignSections(data, live, mode) {
  const { content } = live;
  const compact = mode === 'veteran';
  const sectionStyle = data.sectionStyle;
  const group = (heading, tone, rows, image) => {
    const id = sectionStyle.headings[heading];
    if (!id || !sectionStyle.tones[tone]) throw new Error('Unknown campaign section: ' + heading + ' / ' + tone);
    return {
      id, tone,
      title: Object.fromEntries(sectionLanguages.map(language => [language, data.catalog.ui[heading]?.[language] ?? heading])),
      collapsed: false,
      rows: rows.map(([row, path, checkId]) => ({
        id: row.id || row.checkId || checkId || path.join('.'),
        ...(row.checkId || checkId ? { checkId: row.checkId || checkId } : {}),
        ...(row.kind ? { kind: row.kind } : {}),
        text: Object.fromEntries(sectionLanguages.map(language => [language, row[language]])),
        ...(row.termRefs ? { termRefs: row.termRefs } : {}),
        ...(row.accents ? { accents: row.accents } : {}),
        ...(row.bossId ? { bossId: row.bossId } : {}),
        path,
      })),
      ...(image ? { image: { asset: 'images/' + image, position: 'after_rows' } } : {}),
    };
  };
  if (content.landmarks) {
    const lead = compact ? 'compact' : 'text';
    const variant = compact ? 'compact' : 'body';
    const stops = name => content[name].map((stop, index) => [stop[variant], [name, index, variant], stop.checkId]);
    return [
      group('Layout', 'info', [[content[lead], [lead], 'route:' + live.id], ...stops('landmarks')],
        compact ? null : content.image),
      group('Optionale Ziele', 'optional', stops('optionalStops')),
    ].filter(section => section.rows.length);
  }
  const metadata=new Map((content.sharedSections?.[mode]||[]).map(section=>[section.id,section]));
  const positions=new Map([...metadata.keys()].map((id,index)=>[id,index]));
  const sections=content.sections.map((section,sectionIndex)=>({section,sectionIndex}));
  if (positions.size) sections.sort((a,b)=>(positions.get(sectionStyle.headings[a.section.heading])??Infinity)-(positions.get(sectionStyle.headings[b.section.heading])??Infinity));
  return sections.map(({section, sectionIndex}) => {
    const rows = compact ? content.steps.flatMap((row, index) =>
      row.section === section.heading ? [[row, ['steps', index]]] : [])
      : section.lines.map((row, index) => [row, ['sections', sectionIndex, 'lines', index]]);
    const view=group(section.heading, section.tone, rows, compact ? null : section.image);
    const shared=metadata.get(view.id);
    return shared?{...view,...shared,rows:view.rows}:view;
  }).filter(section => section.rows.length || section.image || (content.template && metadata.has(section.id)));
}

export function lookupArea(index, name, preferredAct) {
  const key = zoneKey(name);
  if (!key) return null;
  const ordered = [...(index.get(preferredAct) ?? []), ...[...index.values()].flat()];
  return ordered.find(zone => zone.key === key)
    ?? ordered.find(zone => zone.aliases.has(key)) ?? null;
}

export const idFor = (_area, item) => `${item.cue !== undefined ? 'route' : 'boss'}:${item.id}`;
export const checked = (prefs, area, item) => prefs.checks[idFor(area, item)] === true;

export function suggestedAction(area, prefs, data) {
  if (!area) return null;
  const live = overlayContent(data, area);
  if (live) {
    const sections = campaignSections(data, live, prefs.mode);
    for (const id of ['quest', 'layout']) {
      const row = sections.find(section => section.id === id)?.rows.find(row => row.checkId && !prefs.checks[row.checkId]);
      if (row) return row.text[prefs.language];
    }
    return null;
  }
  const quest = area.clues.find(clue => clue.mandatory && !layoutKinds.has(clue.kind)
    && !bossKinds.has(clue.kind) && !checked(prefs, area, clue));
  if (quest) return clueTitle(quest);
  const boss = area.bosses.find(item => item.required && !checked(prefs, area, item));
  if (boss) return tr(`${boss.name} besiegen`, `Defeat ${boss.name}`);
  const pending = area.clues.find(clue => !checked(prefs, area, clue)
    && clue.status !== 'test' && !bossKinds.has(clue.kind));
  return pending ? clueTitle(pending) : null;
}

export function actionForRun(data, index, run, prefs) {
  if (run.next) return run.next;
  const area = lookupArea(index, run.zone, prefs.act);
  if (!run.atlasKind) return suggestedAction(area, prefs, data);
  const arena = data.arenas.arenas.find(item => item.phase === 'endgame'
    && item.areas.some(name => zoneKey(name) === zoneKey(run.zone)));
  if (arena) return tr(`${arena.name}: ${arena.response} · EN`, `${arena.name}: ${arena.response}`);
  if (run.atlasKind === 'hub') return tr('Doryani ansprechen und die erste Waystone öffnen.', 'Talk to Doryani and open your first Waystone.');
  const stage = data.atlas.progression.stages.find(item => run.mapTier >= item.min_tier && run.mapTier <= item.max_tier);
  return stage?.quick.basis[0] ? tr(`${stage.quick.basis[0]} · EN`, stage.quick.basis[0]) : null;
}
