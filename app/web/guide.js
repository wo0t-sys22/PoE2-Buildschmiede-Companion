import { esc, tr, zoneKey, unknown, icon, badge, sourceLinks, expand, list, coloredText, termKey, termRoles, RELEASE_VERSION } from './core.js';
import { cueEnglish, stageEnglish } from './translations.js';

export const acts = ['Act 1', 'Act 2', 'Act 3', 'Act 4', 'Act 5', 'Act 6'];
export const buildInfo = {
  'whirling-assault': { className: 'Monk', icon: 'builds', label: 'Whirling Assault', tone: 'jade' },
  'varashta-archon': { className: 'Varashta', icon: 'spark', label: 'Archon Djinn', tone: 'gold' },
  'tactician-supporting-fire': { className: 'Tactician', icon: 'target', label: 'Supporting Fire', tone: 'rust' },
  'twister-spirit-walker': { className: 'Huntress', icon: 'wind', label: 'Twister · Spirit Walker', tone: 'violet' },
};
export const actLabel = act => act === 'Interludes' ? tr('Zwischenspiele', 'Interludes', 'Interludes')
  : tr(act.replace('Act', 'Akt'), act, act);
const layoutKinds = new Set(['Wegsignal', 'Layoutregel', 'Gebietseingang', 'Hörhinweis', 'Abstecher für Spirit']);
const bossKinds = new Set(['Boss-Check', 'Optionaler Boss']);
const includeClue = clue => !['blind', 'skip'].includes(clue.status);

export function clueCategory(clue) {
  if (clue.kind === 'Hörhinweis') return tr('Hören', 'Audio cue', 'Audio');
  if (/permanent/i.test(clue.kind)) return tr('Permanenter Bonus', 'Permanent bonus', 'Perma-Bonus');
  if (clue.mandatory) return tr('Pflicht', 'Required');
  if (bossKinds.has(clue.kind)) return tr('Boss-Hinweis', 'Boss cue');
  if (layoutKinds.has(clue.kind)) return tr('Wegsignal', 'Route cue', 'Layout');
  return tr('Optional', 'Optional');
}

export function clueTitle(clue) {
  return tr(clue.cue, cueEnglish[clue.id] || clue.cue);
}

function clueStatus(clue) {
  const map = {
    test: [tr('Zu testen', 'To test'), 'gold'], observed: [tr('Beobachtet', 'Observed'), 'jade'],
    reference: ['0.5.5f', 'neutral'], rule: ['Training', 'neutral'],
    confirmed: [tr('Bestätigt', 'Confirmed'), 'jade'],
    provisional: [tr('Vorläufig', 'Provisional'), 'gold'],
  };
  return map[clue.status] ?? [unknown(), 'neutral'];
}

function chapter(value) {
  return value.startsWith('Interlude') ? 'Interludes' : value;
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
      const area = find(chapter(clue.act), zone, aliases);
      area?.clues.push(clue);
    }
  }
  for (const boss of data.companion.bosses) {
    const act = chapter(boss.act);
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
    for (const zone of shared.zones) find(chapter(shared.act),zone,shared.aliases?.[zone]||[]);
  }
  return new Map([...areas].map(([act, zones]) => [act, [...zones.values()]]));
}

// Structured area pages take precedence over the legacy clue renderer in the HUD.
export function editorPalette(data) {
  return { ...data.guide.palette, info: '#87ecff', blue: '#8eb6ff', gold: '#e1c887' };
}

export function previewText(row, data, language) {
  const palette = { ...editorPalette(data), ...data.sectionStyle.termOverrides };
  const roles = termRoles(data.termCatalog, language);
  for (const [phrase, ident] of Object.entries(row.termRefs?.[language] ?? {})) {
    const term = data.termCatalog[ident];
    if (term) roles.set(termKey(phrase), term.role);
  }
  for (const [phrase, role] of Object.entries(row.accents?.[language] ?? {})) {
    roles.set(termKey(phrase), role);
  }
  return coloredText(row[language], roles, palette);
}

export function contentEditButton(ctx, collection, id, path, original, label = tr('Bearbeiten', 'Edit')) {
  if (!ctx.editorEnabled) return '';
  const target = JSON.stringify({ collection, id, path });
  return '<button type="button" class="button secondary" data-edit-content="' + esc(target)
    + '"' + (original === undefined ? '' : ' data-edit-original="' + esc(original) + '"')
    + '>' + label + '</button>';
}

export function guideEditRow(data, collection, id, path) {
  return data.catalog[collection]?.[id]?.[path.join('/')] ?? null;
}

function guideLine(ctx, collection, id, path, original, format = esc) {
  const { data, prefs: { language } } = ctx;
  const row = guideEditRow(data, collection, id, path);
  const html = row?.[language] === undefined ? format(original) : previewText(row, data, language);
  const button = contentEditButton(ctx, collection, id, path, original);
  return button ? '<span class="editable-guide-line"><span>' + html + '</span>' + button + '</span>' : html;
}

export function areaNote(ctx, area) {
  if (!area?.clientId) return '';
  const path = [ctx.prefs.mode];
  const row = guideEditRow(ctx.data, 'areaNotes', area.clientId, path);
  const text = row?.[ctx.prefs.language];
  if (!text && !ctx.editorEnabled) return '';
  const empty = tr('Gebietshinweis hinzufügen', 'Add area note');
  return '<section class="panel section-panel"><h3>' + tr('Gebietshinweis', 'Area note') + '</h3>'
    + (text ? '<p>' + guideLine(ctx, 'areaNotes', area.clientId, path, '') + '</p>'
      : contentEditButton(ctx, 'areaNotes', area.clientId, path, '', empty))
    + '</section>';
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

const sectionLabels = ['de', 'hybrid', 'en'];

export function campaignSections(data, live, mode) {
  const { content } = live;
  const compact = mode === 'veteran';
  const sectionStyle = data.sectionStyle;
  const group = (heading, tone, rows, image) => {
    const id = sectionStyle.headings[heading];
    if (!id || !sectionStyle.tones[tone]) throw new Error('Unknown campaign section: ' + heading + ' / ' + tone);
    return {
      id, tone,
      title: Object.fromEntries(sectionLabels.map(language => [language, data.catalog.ui[heading]?.[language] ?? heading])),
      collapsed: false,
      rows: rows.map(([row, path, checkId]) => ({
        id: row.id || row.checkId || checkId || path.join('.'),
        ...(row.checkId || checkId ? { checkId: row.checkId || checkId } : {}),
        ...(row.kind ? { kind: row.kind } : {}),
        text: Object.fromEntries(sectionLabels.map(language => [language, row[language]])),
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

export const websiteTransferScopes = ['approved', 'all', ...acts.slice(0, 4)];
export const websiteCampaignStylesheet = 'website-campaign-cards.css';

export function campaignWebsiteExport(data, selection = 'approved') {
  if (!websiteTransferScopes.includes(selection)) throw new Error('Unknown transfer scope: ' + selection);
  const routes = indexGuide(data);
  const pages = new Map();
  const images = new Set();
  const allowed = data.sectionStyle.publication;
  const selected = (act, id, ids) => selection === 'all' || selection === act
    || (selection === 'approved' && ids.includes(id));
  const transferSections = (sections, mode) => sections.map(section => {
    if (section.image) images.add(section.image.asset);
    return { ...section, rows: section.rows.map(({ path, ...row }) => {
      const boss = data.catalog.bossSteps?.[row.checkId];
      const bossId = row.bossId || (row.checkId?.startsWith('boss:') ? row.checkId.slice(5)
        : boss && (!boss.mode || boss.mode === mode) ? boss.id : null);
      return bossId ? { ...row, bossId } : row;
    }) };
  });
  for (const area of [...routes.values()].flat()) {
    const live = overlayContent(data, area);
    if (!live || !selected(area.act, live.id, allowed.areas)) continue;
    if (!pages.has(live.id)) {
      const layouts = Object.fromEntries(['basis', 'veteran'].map(mode =>
        [mode, transferSections(campaignSections(data, live, mode), mode)]));
      pages.set(live.id, { id: live.id, act: area.act, zones: [], aliases: {}, status: 'live',
        editorApproved: allowed.areas.includes(live.id), layouts,
        ...(live.content.template ? { template: true, title: live.content.title } : {}) });
    }
    const page = pages.get(live.id);
    page.zones.push(area.name);
    page.aliases[area.name] = [...area.aliases];
  }
  const towns = Object.entries(data.catalog.townTips).flatMap(([id, town]) => {
    const act = typeof town.act === 'number' ? 'Act ' + town.act : town.act;
    if (!selected(act, id, allowed.towns)) return [];
    const module = ids => ids.map(key => ({ id: key, status: 'live', layouts: data.catalog.townTipPool[key] }));
    const name = lookupArea(routes, town.zones[0], act)?.name ?? town.zones[0];
    return [{ id, act, zones: town.zones, name, status: 'live', editorApproved: allowed.towns.includes(id),
      tone: 'gameplay_title', collapsed: true,
      defaults: module(town.defaults), more: module(town.more) }];
  });
  return {
    schema: 'buildschmiede.campaign.live.v2',
    scope: 'structured_campaign_pages_and_town_tips',
    source: { version: RELEASE_VERSION, selection },
    assets: { stylesheet: websiteCampaignStylesheet, images: [...images] },
    presentation: {
      variants: ['basis', 'veteran'], languages: sectionLabels, tones: data.sectionStyle.tones,
      termColors: { ...editorPalette(data), ...data.sectionStyle.termOverrides },
    },
    terms: data.termCatalog,
    importPolicy: {
      operation: 'upsert_live_by_id',
      missingRecords: 'preserve',
      preserveOrder: ['layouts.*', 'layouts.*.rows', 'towns.defaults', 'towns.more'],
    },
    pages: [...pages.values()],
    towns,
  };
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

export function areaGroups(area, mode) {
  const priority = (a, b) => Number(b.mandatory) - Number(a.mandatory)
    || Number(a.status === 'test') - Number(b.status === 'test');
  const quest = area.clues.filter(clue => !layoutKinds.has(clue.kind) && !bossKinds.has(clue.kind)).sort(priority);
  const layout = area.clues.filter(clue => layoutKinds.has(clue.kind)).sort(priority);
  const cues = area.clues.filter(clue => bossKinds.has(clue.kind)).sort(priority);
  if (!layout.length && quest[0]?.kind === 'Fortschritt' && mode === 'basis') {
    layout.push(quest[0]);
  }
  return { quest, layout, cues };
}

function highlighted(instruction, focus, format) {
  const index = focus ? instruction.indexOf(focus) : -1;
  if (index < 0) return format(instruction);
  return format(instruction.slice(0, index)) + '<mark class="route-highlight">' + format(focus)
    + '</mark>' + format(instruction.slice(index + focus.length));
}

export function clueRow(clue, area, ctx) {
  const { data, prefs } = ctx;
  const [status, tone] = clueStatus(clue);
  const title = clueTitle(clue);
  const translation = data.catalog.routes?.[clue.id]?.[prefs.language];
  const localized = { ...clue, ...translation };
  const formatTerm = text => previewText({ [prefs.language]: text }, data, prefs.language);
  const line = (path, original, format) => guideLine(ctx, 'routeEdits', clue.id, path, original, format);
  const focused = text => highlighted(text, localized.highlight, formatTerm);
  const details = (field, css = '', format = formatTerm) => localized[field]
    ? `<p class="${css}">${line([field], localized[field], format)}</p>` : '';
  const original = prefs.language === 'en' && !translation
    ? '<span class="copy-label">R17 · DE</span>' : '';
  const expanded = original + details('instruction', '', focused) + details('target', 'muted')
    + details('gameplayTip') + details('campsiteTip') + details('mudBurrowTip') + details('note', 'muted')
    + details('veteranText', 'muted', focused);
  const summary = [...new Set([localized.cue, localized.target].filter(Boolean))].join(' → ');
  const compact = localized.compactSteps?.map((step, index) => [step, ['compactSteps', index]])
    ?? [[summary, ['compact']]];
  const quick = prefs.mode === 'veteran' ? compact.filter(([step]) => step)
    .map(([step, path]) => `<p class="clue-quick">${line(path, step, focused)}</p>`).join('') : '';
  return `<div class="clue-row no-check${checked(prefs, area, clue) ? ' is-done' : ''}">
    <div class="clue-copy">
      <div class="clue-name">${line(['cue'], translation?.cue ?? title, formatTerm)}</div>
      ${quick}
      ${expanded ? expand(tr('Details', 'Details'), expanded, prefs.mode === 'basis') : ''}
    </div>
    <div class="clue-badges">${badge(clueCategory(clue), /permanent/i.test(clue.kind) ? 'jade' : 'neutral')}${badge(status, tone)}</div>
  </div>`;
}

export function bossRow(boss, ctx) {
  const { prefs, data } = ctx;
  const translation = data.bossLanguages?.[boss.id]?.[prefs.language];
  if (translation) boss = { ...boss, ...translation, attacks: translation.attacks
    ? translation.attacks.map((attack, index) => ({ ...boss.attacks?.[index], ...attack }))
    : boss.attacks };
  const formatTerm = text => previewText({ [prefs.language]: text }, data, prefs.language);
  const line = (path, original) => guideLine(ctx, 'bossEdits', boss.id, path, original, formatTerm);
  const field = (key, prefix = '', original = boss[key]) =>
    (guideEditRow(data, 'bossEdits', boss.id, [key])?.[prefs.language] ?? original)
      ? `<p>${prefix}${line([key], original ?? '')}</p>` : '';
  const card = (title, body, tone = 'gold', open = true) => body
    ? `<details class="panel section-panel editorial-preview guide-section" style="--section-tone:${esc(data.sectionStyle.tones[tone])}"
        ${open ? 'open' : ''}><summary>${esc(title)}</summary><div class="guide-section-body">${body}</div></details>` : '';
  const attackList = (boss.attacks ?? []).map((attack, index, attacks) => {
    const phase = attack.phase && attack.phase !== attacks[index - 1]?.phase
      ? `<p><strong>${esc(data.catalog.ui?.[attack.phase]?.[prefs.language] ?? attack.phase)}</strong></p>` : '';
    return `${phase}<div class="attack">
    <strong>${line(['attacks', index, 'name'], attack.name)}</strong>
    <span><b class="boss-cue">${tr('Signal', 'Cue')} ·</b> ${line(['attacks', index, 'tell'], attack.tell)}</span>
    <span><b class="boss-response">${tr('Reaktion', 'Response')} ·</b> ${line(['attacks', index, 'answer'], attack.answer)}</span>
  </div>`;
  }).join('');
  const prep = field('prep');
  const tactics = field('plan') + field('window', tr('Konter · ', 'Counter · '));
  const optionalFields = ctx.editorEnabled ? [
    ['prep', tr('Vorbereitung ergänzen', 'Add preparation')],
    ['plan', tr('Kampftaktik ergänzen', 'Add fight tactics')],
  ].filter(([key]) => !field(key)).map(([key, label]) =>
    contentEditButton(ctx, 'bossEdits', boss.id, [key], '', label)).join('') : '';
  const details = [
    card(tr('Vor dem Kampf', 'Before the fight'), prep, 'gameplay_title'),
    card(tr('Kampftaktik', 'Fight tactics'), tactics, 'info'),
    card(tr('Angriffe & Phasen', 'Attacks & phases'), attackList && `<div class="attacks">${attackList}</div>`, 'danger'),
  ].join('');
  const compact = (boss.compactSteps ?? [boss.quick]).map((step, index) => step
    ? `<p class="clue-quick">${line(boss.compactSteps ? ['compactSteps', index] : ['quick'], step)}</p>` : '').join('');
  const reward = boss.rewardText || boss.reward;
  const zone = zoneKey(boss.zone);
  const areaTerm = () => Object.values(data.termCatalog ?? {}).find(term =>
    ['blue', 'info'].includes(term.role) && term.labels?.en && zoneKey(term.labels.en) === zone);
  const location = data.catalog.areas?.[zone]?.[prefs.language] ?? areaTerm()?.labels[prefs.language] ?? boss.zone;
  const kind = boss.rewardKind;
  const title = kind === 'progress' ? tr('Fundort & Fortschritt', 'Location & progression')
    : ['none', 'nearby'].includes(kind) ? tr('Fundort', 'Location') : tr('Fundort & Belohnung', 'Location & reward');
  const label = ({ drop: tr('Beute', 'Drop'), quest: tr('Questbelohnung', 'Quest reward'),
    nearby: tr('In der Nähe', 'Nearby'), progress: tr('Fortschritt', 'Progression') })[kind] ?? tr('Belohnung', 'Reward');
  const target = lookupArea(ctx.index, boss.zone, chapter(boss.act));
  const footer = `<p><button type="button" class="button secondary" data-zone="${esc(target?.name ?? boss.zone)}"
      data-act="${esc(chapter(boss.act))}">${esc(location)} →</button></p>`
    + (kind === 'none' ? '' : field('rewardText', `<b class="boss-cue">${label} ·</b> `, reward))
    + field('afterFight', tr('Nach dem Sieg · ', 'After the victory · '));
  return `<div class="clue-row no-check">
    <div class="clue-copy"><div class="clue-name">${esc(boss.name)}</div>
      ${prefs.mode === 'veteran' ? card(tr('Kampf auf einen Blick', 'Fight at a glance'),
        compact, 'info') + expand(tr('Details anzeigen', 'Show details'), details)
        : details + (ctx.editorEnabled ? expand(tr('Kompakttext', 'Compact text'), compact) : '')}
      ${card(title, footer, 'quest')}
      ${optionalFields ? expand(tr('Redaktionelle Ergänzungen', 'Editorial additions'), optionalFields) : ''}
      ${card(tr('Quellen', 'Sources'), sourceLinks(boss.sources, data.companion.sources), 'gameplay_title', false)}
    </div>
    <div class="clue-badges">${badge(boss.required ? tr('Pflicht', 'Required') : tr('Optional', 'Optional'), boss.required ? 'rust' : 'neutral')}</div>
  </div>`;
}

export function linkedBuildId(hash) {
  return /^#builds\/([a-z0-9]+(?:-[a-z0-9]+)*)$/.exec(hash)?.[1] ?? null;
}

export function orderedBuilds(builds) {
  return [...Object.keys(buildInfo)].map(id => builds.find(build => build.id === id)).filter(Boolean)
    .concat(builds.filter(build => !buildInfo[build.id]));
}

export function stageLabel(build, stage) {
  return tr(stage.label, stageEnglish[`${build.id}:${stage.id}`]?.[0] || stage.label);
}

export function stageNext(build, stage) {
  return tr(stage.next, stageEnglish[`${build.id}:${stage.id}`]?.[1] || stage.next);
}

export function autoStage(build, level) {
  return [...build.stages].reverse().find(stage => level !== null && level >= stage.min_level) ?? build.stages[0];
}

export function groupCard(iconName, label, values, verbose, sourceLanguage) {
  return `<article class="panel small-panel"><header class="section-head">${icon(iconName)}<h3>${esc(label)}</h3></header>
    ${sourceLanguage ? `<span class="copy-label">R17 · ${sourceLanguage}</span>` : ''}
    ${list(verbose ? values : values?.slice(0, 1))}
    ${!verbose && values?.length > 1 ? expand(tr('Weitere Hinweise', 'More notes'), list(values.slice(1))) : ''}
  </article>`;
}
