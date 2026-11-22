import { badge, esc, expand, externalUrl, icon, itemText, sourceLinks, timeLabel, tr, unknown, zoneKey } from './core.js';
import { clueTitle, idFor, contentEditButton, previewText } from './guide.js';

export function hubKind(guide, zone) {
  const key = zoneKey(zone);
  return Object.entries(guide.hubs).find(([, names]) => names.some(name => zoneKey(name) === key))?.[0]
    ?? (/\b(?:hideout|versteck)\b/.test(key) ? 'hideout' : null);
}

export function contextTips(guide, zone) {
  const hub = hubKind(guide, zone);
  const key = zoneKey(zone);
  return guide.tips.filter(tip => tip.at.includes(hub) || tip.at.includes(key === 'clearfell' ? 'clearfell zone' : key));
}

function panelTitle(symbol, title, suffix = '') {
  return `<header class="section-head">${icon(symbol)}<h2>${esc(title)}</h2>${suffix}</header>`;
}

const local = value => tr(value.de, value.en);

function tipsList(guide, zone) {
  return contextTips(guide, zone).map(tip => expand(local(tip.title), `<p>${itemText(local(tip.body))}</p>`)).join('');
}

export function beginnerPanel(ctx, zone) {
  const { catalog } = ctx.data;
  const town = Object.entries(catalog.townTips ?? {}).find(([, entry]) => entry.zones.includes(zoneKey(zone)));
  if (town) {
    const [id, { defaults, more }] = town;
    const index = ctx.townTip?.id === id ? ctx.townTip.index : -1;
    const pool = catalog.townTipPool;
    const tipRow = tip => previewText(pool[tip][ctx.prefs.mode], ctx.data, ctx.prefs.language)
      + contentEditButton(ctx, 'townTipPool', tip, [ctx.prefs.mode]);
    const label = index < 0 ? 'Weitere Tipps' : index < more.length - 1 ? 'Nächster Tipp' : 'Zusatz-Tipp schließen';
    const extra = index >= 0 ? '<div class="town-extra-tip"><h3>'
      + esc(catalog.ui['Zusatz-Tipp'][ctx.prefs.language]) + '</h3><p>' + tipRow(more[index]) + '</p></div>' : '';
    return '<details class="panel section-panel editorial-preview guide-section" data-section="tips" style="--section-tone:'
      + esc(ctx.data.sectionStyle.tones.gameplay_title) + '"><summary>' + tr('Tipps', 'Tips')
      + '</summary><ul>' + defaults.map(tip => '<li>' + tipRow(tip) + '</li>').join('') + '</ul>' + extra
      + (more.length ? '<button class="button secondary" type="button" data-town-tip="' + esc(id)
        + '">' + esc(catalog.ui[label][ctx.prefs.language]) + '</button>' : '') + '</details>';
  }
  if (ctx.prefs.mode !== 'basis') return '';
  const tips = tipsList(ctx.data.guide, zone);
  return tips ? `<section class="panel section-panel r18-panel">${panelTitle('spark', tr('Einsteiger-Tipps', 'Beginner tips'))}${tips}</section>` : '';
}

function hotkeyRow(row) {
  const keys = tr(row.key, row.key.replaceAll('Strg', 'Ctrl').replaceAll('Linksklick', 'Left click')
    .replaceAll('Rechtsklick', 'Right click').replaceAll('Leertaste', 'Space'));
  return `<div class="hotkey-row"><kbd>${esc(keys)}</kbd><span>${itemText(local(row))}</span>
    ${row.verify ? badge(tr('Zu testen', 'To test'), 'gold') : ''}</div>`;
}

export function hotkeysPanel(ctx, zone) {
  const { guide } = ctx.data;
  const hub = hubKind(guide, zone);
  const quick = (guide.quick_contexts[hub] ?? guide.quick_contexts.clearfell).map(id => hotkeyRow(guide.quick_keys[id])).join('');
  const byGroup = Object.entries(guide.hotkey_groups).map(([group, title]) =>
    expand(local(title), guide.hotkeys.filter(row => row.group === group).map(hotkeyRow).join('')));
  const instructions = tr('Tastatur und Maus. Eigene Belegungen stehen im Spiel unter Optionen → Eingabe.',
    'Keyboard and mouse. Check your bindings in Options → Input.');
  return `<section class="panel section-panel r18-panel">${panelTitle('terminal', tr('Hotkeys', 'Hotkeys'), hub ? badge(zone, 'jade') : '')}
    <div class="hotkey-quick">${quick}</div>
    ${expand(tr('Alle Hotkeys für Tastatur und Maus', 'All keyboard and mouse shortcuts'),
      `<p class="muted">${instructions}</p>${byGroup.join('')}${sourceLinks(['hotkeys', 'stash', 'bulk'], guide.sources)}`)}
  </section>`;
}

export function checklistPanel(ctx, area, zone) {
  const curated = (area?.clues ?? []).map(clue => ctx.data.guide.areaChecklists?.[clue.id]).find(Boolean);
  let tasks;
  if (curated) {
    tasks = curated.map(row => ({ id: row.id, title: local(row.title) }));
  } else {
    tasks = contextTips(ctx.data.guide, zone).filter(tip => tip.scope !== 'tip')
      .map(tip => ({ id: tip.scope + ':' + tip.id, title: local(tip.title), setup: tip.scope === 'setup' }));
    for (const clue of area?.clues ?? []) {
      if (clue.mandatory || /permanent/i.test(clue.kind)) {
        tasks.push({ id: idFor(area, clue), title: clueTitle(clue), verify: clue.status === 'test' });
      }
    }
    for (const boss of area?.bosses ?? []) {
      if (boss.required) tasks.push({ id: idFor(area, boss), title: tr(`${boss.name} besiegen`, `Defeat ${boss.name}`) });
    }
  }
  const checks = ctx.prefs.checks;
  const count = tasks.filter(task => checks[task.id]).length;
  return `<section class="panel section-panel r18-panel">
    ${panelTitle('check', tr('Checkliste', 'Checklist'), badge(`${count} / ${tasks.length}`, 'jade'))}
    <div class="checklist-profile"><span>${esc(ctx.run.character || tr('Aktiver Run', 'Active run'))}</span>
      <button type="button" class="text-link" data-new-checklist>${tr('Neue Run-Checkliste', 'New run checklist')}</button></div>
    ${tasks.map(task => `<div class="clue-row checklist-row${checks[task.id] ? ' is-done' : ''}">
      <label class="check"><input type="checkbox" data-check="${esc(task.id)}" aria-label="${esc(task.title)}"${checks[task.id] ? ' checked' : ''}><span>${icon('check')}</span></label>
      <div class="clue-copy"><strong>${itemText(task.title)}</strong></div>
      ${task.setup ? badge(tr('Einmalig', 'Once'), 'neutral') : task.verify ? badge(tr('Zu testen', 'To test'), 'gold') : ''}
    </div>`).join('') || `<p class="empty">${tr('Für dieses Gebiet sind keine Aufgaben hinterlegt.', 'There are no tasks for this area.')}</p>`}
  </section>`;
}

export function upgradesPanel(ctx, buildId = '') {
  const { guide } = ctx.data;
  const milestones = guide.upgrades.filter(row => row.scope === 'general' || row.scope === buildId);
  const search = guide.search[buildId] ?? guide.search.general;
  return `<section class="panel section-panel r18-panel">
    ${panelTitle('gem', tr('Wann sich ein Upgrade lohnt', 'When to upgrade'))}
    <div class="upgrade-list">${milestones.map(row => expand(local(row.title),
      `<p>${itemText(local(row.body))}</p>${sourceLinks([row.source], guide.sources)}`)).join('')}</div>
    <div class="inline-actions vendor-search">
      <button type="button" class="text-link" data-copy="${esc(search.de)}">${icon('copy')}${tr('Händlersuche DE', 'Vendor search DE')}</button>
      <button type="button" class="text-link" data-copy="${esc(search.en)}">${icon('copy')}${tr('Händlersuche EN', 'Vendor search EN')}</button>
    </div>
  </section>`;
}

export function raceControls(ctx) {
  const state = ctx.nativeState;
  const checkpoints = state?.checkpoints ?? [];
  const splits = (state?.checkpointRuns ?? []).slice(-5).reverse();
  const names = new Map(checkpoints.map(row => [row.id, row.name]));
  return `<section class="panel section-panel r18-panel race-panel">
    ${panelTitle('clock', tr('Race-Timer und Splits', 'Race timer and splits'))}
    <div class="inline-actions">
      <button class="button primary" type="button" data-timer="toggle">${icon('clock')}${ctx.run.live ? tr('Pausieren', 'Pause') : tr('Timer starten', 'Start timer')}</button>
      <button class="button secondary" type="button" data-timer="reset">${tr('Auf null setzen', 'Reset timer')}</button>
    </div>
    ${checkpoints.length ? `<form id="split-form" class="inline-actions">
      <label class="select-label">Checkpoint<select name="checkpointId" required>
        ${checkpoints.map(row => `<option value="${esc(row.id)}">${esc(row.name)}</option>`).join('')}</select></label>
      <button class="button secondary" type="submit">${tr('Split speichern', 'Save split')}</button>
    </form>` : ''}
    ${splits.length ? `<ul class="points">${splits.map(split => `<li>${esc(names.get(split.checkpointId) ?? split.checkpointId)} · ${timeLabel(split.seconds)}</li>`).join('')}</ul>` : ''}
    <div class="source-links"><a href="./klassisch.html" target="_blank" rel="noopener">${tr('Klassische Race Control · Legacy', 'Classic Race Control · Legacy')}${icon('link')}</a></div>
  </section>`;
}

export function rankTable(group) {
  const unknownTier = () => badge(tr('Zu testen', 'To test'), 'gold');
  return `<div class="tier-group">
    <div class="source-links">${group.sources.map(source => {
      const url = externalUrl(source.url);
      return url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(source.label)}${icon('link')}</a>` : '';
    }).join('')}</div>
    ${group.restriction ? `<p class="muted">${esc(group.restriction)}</p>` : ''}
    <div class="table-wrap"><table><thead><tr><th scope="col">${tr('Rang', 'Rank')}</th><th scope="col">Ingame</th><th scope="col">iLvl</th><th scope="col">Roll</th></tr></thead>
      <tbody>${group.rows.map(row => `<tr><td>#${row.rank}</td><td>${row.game_tier ? 'T' + row.game_tier : unknownTier()}</td>
        <td>${row.ilvl ?? unknown()}</td><td><span class="tier-name">${esc(row.name)}</span>${itemText(row.roll, 'mod')}</td></tr>`).join('')}</tbody>
    </table></div>
    ${group.count === 2 ? `<p class="muted">${tr('Dieser Affix-Pool hat zwei Stufen.', 'This affix pool has two tiers.')}</p>` : ''}
  </div>`;
}
