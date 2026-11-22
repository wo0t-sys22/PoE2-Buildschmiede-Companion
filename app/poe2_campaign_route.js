const campaignRouteLabels = {
  story: 'Pflicht',
  audio: 'Hören',
  route: 'Wegsignal',
  bonus: 'Bonus',
  sideboss: 'Optionaler Boss',
  optional: 'Optional',
  test: 'Suchhilfe',
};

function campaignGuideMode(value) {
  return value === 'veteran' ? 'veteran' : 'basis';
}

function campaignRouteCategory(clue) {
  if (/permanent/i.test(clue.kind || '')) return 'bonus';
  if (clue.kind === 'Hörhinweis') return 'audio';
  if (clue.status === 'test') return 'test';
  if (clue.mandatory) return 'story';
  if (clue.kind === 'Wegsignal') return 'route';
  if (/^optionaler boss/i.test(clue.kind || '')) return 'sideboss';
  return 'optional';
}

function campaignRouteBadge(clue) {
  const status = {
    confirmed: 'Bestätigt',
    provisional: 'Vorläufig',
    blind: 'Blind',
    observed: 'Beobachtet',
    skip: 'Zurückstellen',
    reference: '0.5.5f',
    rule: 'Training',
  };
  const category = campaignRouteCategory(clue);
  const label = campaignRouteLabels[category];
  if (category === 'audio' && clue.status === 'observed') return `${label} · beobachtet`;
  return category === 'test' ? label : `${label} · ${status[clue.status] || 'Offen'}`;
}

function campaignLiveLabel(clue) {
  const category = campaignRouteCategory(clue);
  const label = campaignRouteLabels[category];
  return category === 'audio' && clue.status === 'observed' ? `${label} · beobachtet` : label;
}

function campaignLiveText(clue) {
  if (clue.veteranText) return clue.veteranText;
  if (['audio', 'route', 'test'].includes(campaignRouteCategory(clue)) && clue.instruction) {
    return clue.instruction;
  }
  return [clue.cue, clue.target].filter(Boolean).join(' · ');
}

function campaignInstructionHtml(clue, escapeHtml) {
  const instruction = String(clue.instruction ?? '');
  const highlight = clue.highlight;
  const start = typeof highlight === 'string' && highlight ? instruction.indexOf(highlight) : -1;
  if (start === -1) return escapeHtml(instruction);

  const end = start + highlight.length;
  return `${escapeHtml(instruction.slice(0, start))}<mark class="route-highlight">${escapeHtml(highlight)}</mark>${escapeHtml(instruction.slice(end))}`;
}

function campaignZoneKey(value) {
  return String(value || '').trim().toLowerCase().replace(/’/g, "'").replace(/^the /, '');
}

function campaignRouteClues(clues, zone) {
  const value = campaignZoneKey(zone);
  if (!value) return [];

  const priority = {story: 0, audio: 1, route: 2, test: 2, bonus: 3, optional: 4, sideboss: 5};
  return (clues || []).filter(clue => {
    if (clue.status === 'skip' || clue.status === 'blind') return false;
    const matches = Array.isArray(clue.zoneMatch) && clue.zoneMatch.length ? clue.zoneMatch : [clue.zone];
    const keys = matches.map(campaignZoneKey);
    return clue.exactZone ? keys.includes(value) : keys.some(key => key && value.includes(key));
  }).sort((a, b) => {
    const rank = clue => {
      const category = campaignRouteCategory(clue);
      return category === 'test' && !clue.veteranText ? 6 : priority[category];
    };
    return rank(a) - rank(b);
  });
}

const campaignLayoutKinds = new Set(['Wegsignal', 'Layoutregel', 'Gebietseingang', 'Hörhinweis', 'Abstecher für Spirit']);

function campaignQuestClues(clues) {
  return clues.filter(clue => !campaignLayoutKinds.has(clue.kind) &&
    !['Boss-Check', 'Optionaler Boss'].includes(clue.kind));
}

function campaignObjective(state, zone, bosses = []) {
  const goal = state.progress?.nextAction;
  if (goal && goal !== 'Route und Build vorbereiten') return goal;
  const matches = campaignRouteClues(state.routeClues, zone);
  const quest = campaignQuestClues(matches);
  const primary = quest.find(clue => clue.mandatory);
  if (primary) return primary.cue;
  const boss = bosses.find(boss => boss.required);
  if (boss) return `${boss.name} besiegen`;
  return quest[0]?.cue || matches[0]?.cue || '';
}

function campaignRouteBlocks(clues, zone, mode) {
  const matches = campaignRouteClues(clues, zone);
  let quest = campaignQuestClues(matches);
  let layout = matches.filter(clue => campaignLayoutKinds.has(clue.kind));
  if (!layout.length && quest[0]?.kind === 'Fortschritt') {
    layout = [quest[0]];
    quest = quest.slice(1);
  }
  if (campaignGuideMode(mode) === 'veteran') {
    quest = quest.filter(clue => clue.mandatory || /permanent/i.test(clue.kind || '')).slice(0, 3);
  }
  return {layout, quest};
}
