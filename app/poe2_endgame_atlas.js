class AtlasGuide {
  constructor(escapeHtml, { separate = false, section = "campaign", onBuildChange, content = "all" } = {}) {
    this.esc = escapeHtml;
    this.mode = 'basis';
    this.section = section;
    this.separate = separate;
    this.onBuildChange = onBuildChange;
    this.content = content;
    this.tab = content === 'build' ? 'build' : 'progression';
    this.stage = '';
    this.slot = '';
    this.affixBuild = '';
    this.craftView = 'steps';
    this.layer = '';
    this.tabletView = 'presets';
    this.tabletType = '';
    this.preset = '';
    this.affixPage = 0;
    this.tabletPage = 0;
    this.guideBuild = '';
    this.guideStage = '';
    this.guideRecipe = '';
    this.lowerTiers = false;
    this.lastEntry = null;
  }

  attach(root, campaign, onSwitch) {
    this.campaign = campaign;
    this.onSwitch = onSwitch;
    if (root === this.root) return;
    this.root = root;
    if (!root) return;
    this.root.addEventListener('click', event => this.click(event));
    this.root.addEventListener('change', event => this.change(event));
    this.render();
  }

  observe(location, mode) {
    const changedMode = this.mode !== (mode === 'veteran' ? 'veteran' : 'basis');
    this.mode = mode === 'veteran' ? 'veteran' : 'basis';
    if (location) {
      const entry = location.entry || '';
      if (entry && entry !== this.lastEntry && location.kind) {
        this.section = 'endgame';
        this.lastEntry = entry;
        this.lastKind = location.kind;
        this.render();
        return;
      }
      this.lastEntry = entry;
      if (!location.kind && location.campaign && this.lastKind && this.section === 'endgame') {
        this.lastKind = location.kind;
        this.show('campaign');
        return;
      }
      if (location.kind || location.campaign) this.lastKind = location.kind;
    }
    if (changedMode && this.section === 'endgame') this.render();
  }

  show(section, tab = this.tab) {
    this.section = section;
    this.tab = tab;
    this.render();
  }

  selectBuild(id = '') {
    if (this.guideBuild === id) return;
    this.guideBuild = id;
    this.guideStage = '';
    this.guideRecipe = '';
    if (this.section === 'endgame' && this.tab === 'build') {
      const panel = this.root?.querySelector('.atlas-panel');
      if (panel) panel.scrollTop = 0;
      this.render();
    }
  }

  async load() {
    if (this.loading || this.data) return;
    this.loading = true;
    this.loadError = false;
    this.render();
    try {
      const response = await fetch('poe2_endgame_atlas.json', { cache: 'no-store' });
      if (!response.ok) throw new Error('Atlas data request failed');
      const data = await response.json();
      if (data.schema_version !== 1 || !data.progression || !data.crafting || !data.tablets) {
        throw new Error('Atlas data format mismatch');
      }
      this.stage = data.progression.stages[0].id;
      this.slot = data.crafting.slots[0].id;
      this.layer = data.crafting.special_layers[0].id;
      this.tabletType = data.tablets.types[0].id;
      this.preset = data.tablets.presets[0].id;
      this.data = data;
    } catch (_) {
      this.loadError = true;
    } finally {
      this.loading = false;
      this.render();
    }
  }

  button(key, value, label) {
    return `<button type="button" data-atlas-choice="${key}" data-value="${this.esc(value)}" aria-pressed="${this[key] === value}">${this.esc(label)}</button>`;
  }

  group(label, key, items, extraClass = '') {
    return `<div class="atlas-nav ${extraClass}" role="group" aria-label="${this.esc(label)}">${items.map(([value, name]) => this.button(key, value, name)).join('')}</div>`;
  }

  select(label, key, items, current = this[key]) {
    return `<label>${this.esc(label)}<select data-atlas-field="${key}">${items.map(([value, name]) =>
      `<option value="${this.esc(value)}"${current === value ? ' selected' : ''}>${this.esc(name)}</option>`).join('')}</select></label>`;
  }

  list(values, ordered = false) {
    const tag = ordered ? 'ol' : 'ul';
    return `<${tag}>${values.map(value => `<li>${this.esc(value)}</li>`).join('')}</${tag}>`;
  }

  references(ids) {
    const links = ids.map(id => this.data.sources[id]).filter(Boolean).map(source => {
      const label = this.esc(source.label);
      if (!source.url.startsWith('https://')) return label;
      return `<a href="${this.esc(source.url)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    });
    return links.length ? `<details><summary>Sources</summary><p class="atlas-muted">${links.join(' · ')}</p></details>` : '';
  }

  farming(farming) {
    return `<details><summary>Base farming &amp; iLvl breakpoints</summary>
      <p>${this.esc(farming.rule)}</p>
      <ul class="atlas-mod-list">${farming.breakpoints.map(row => `<li>
        <b>iLvl ${this.esc(row.min_ilvl)}</b> · ${this.esc(row.unlocks)}
        <small>Regular maps · ${this.esc(row.standard)}</small>
        ${row.irradiated ? `<small>Irradiated · ${this.esc(row.irradiated)}</small>` : ''}
      </li>`).join('')}</ul>
      <p class="atlas-muted">${this.esc(farming.drop_note)} ${this.esc(farming.early_note)}</p>
      ${this.references(farming.source_ids)}
      </details>`;
  }

  websiteSections(placement) {
    const lang = document.documentElement.lang === 'de' ? 'de' : 'en';
    return (this.data.website_sections ?? []).filter(section => section.placement === placement).map(section =>
      `<details open><summary>${this.esc(section.title[lang])}</summary>
        ${this.list(section.body[lang])}${this.references(section.sources)}</details>`).join('');
  }

  progression() {
    const data = this.data.progression;
    const stage = data.stages.find(item => item.id === this.stage);
    const checkpoints = Object.entries(stage.checkpoints).map(([name, value]) =>
      `<div><dt>${this.esc(name)}</dt><dd>${this.esc(value)}</dd></div>`).join('');
    const slots = data.tablet_slots.map(row => `${row.waystone_mods} mods → ${row.slots} slots`).join(' · ');
    const quick = stage.quick;
    let tips;
    if (quick && this.mode === 'veteran') {
      const decisions = Object.entries(quick.veteran).map(([label, tip]) =>
        `<div><dt${label === 'Reroll' ? ' class="atlas-caution"' : ''}>${this.esc(label)}</dt><dd>${this.esc(tip)}</dd></div>`);
      tips = `<dl class="atlas-decisions">${decisions.join('')}</dl>`;
    } else {
      tips = this.list(quick?.basis ?? stage[this.mode]);
    }
    return `${this.websiteSections('progression')}${this.group('Waystone progression', 'stage', data.stages.map(item => [item.id, item.label]))}
      <dl class="atlas-checkpoints">${checkpoints}</dl>
      ${tips}
      ${quick ? `<p class="atlas-farm"><b>Farm</b> ${this.esc(quick.farm)}</p>` : ''}
      ${data.farming ? this.farming(data.farming) : ''}
      <details><summary>Atlas milestones & Map Device</summary>
        ${this.list(stage.milestones, true)}
        ${quick ? this.list(stage[this.mode]) : ''}
        <p>${this.esc(slots)}. ${this.esc(data.city_bonus)}</p>
        <p class="atlas-muted">${this.esc(data.note)}</p>
      </details>
      ${this.references(data.source_ids)}`;
  }

  affixes(data) {
    const build = data.builds.find(item => item.id === this.affixBuild);
    const groups = build?.affix_groups || (build ? [build.id] : []);
    const matching = data.affixes.filter(mod => mod.slots.includes(this.slot) &&
      (!groups.length || !mod.builds.length || groups.some(group => mod.builds.includes(group))));
    const rows = matching.flatMap(mod => (this.lowerTiers ? mod.tiers : mod.tiers.slice(0, 1))
      .map(tier => ({mod, tier})));
    if (!rows.length) return '<p class="atlas-muted">No curated base affixes for this selection.</p>';
    const pageSize = 5;
    const pages = Math.ceil(rows.length / pageSize);
    return `<div class="atlas-copy-row">
        <p class="atlas-muted">${this.esc(data.tier_note)}</p>
        <button type="button" data-atlas-action="tiers" aria-pressed="${this.lowerTiers}">Lower tiers</button>
      </div>
      ${build ? `<p class="atlas-muted">${this.esc(build.priorities)}</p>` : ''}
      <table class="atlas-table"><thead><tr><th>Affix / Base</th><th>Side</th><th>Tier</th><th>Min. iLvl</th><th>Max Roll</th></tr></thead>
        <tbody>${rows.slice(this.affixPage * pageSize, (this.affixPage + 1) * pageSize).map(({mod, tier}) =>
          `<tr title="${this.esc(tier.roll)}"><td class="atlas-affix"><b>${this.esc(mod.label)}</b><br><small>${this.esc(mod.base)} · ${this.esc(tier.name)}</small></td>
            <td>${this.esc(mod.side)}</td><td>${this.esc(tier.tier)}</td><td>${this.esc(tier.min_ilvl)}</td><td>${this.esc(tier.max_roll)}</td></tr>`).join('')}
        </tbody></table>
      ${this.pager('affixPage', pages)}
      ${this.references(data.source_ids)}`;
  }

  crafting(affixOnly = false) {
    const data = this.data.crafting;
    let body;
    if (!affixOnly && this.craftView === 'layers') {
      const layer = data.special_layers.find(item => item.id === this.layer);
      body = `${this.select('Crafting layer', 'layer', data.special_layers.map(item => [item.id, item.label]))}
        <p>${this.esc(layer[this.mode])}</p>
        <details><summary>Examples & eligible items</summary><ul class="atlas-mod-list">${layer.examples.map(item =>
          `<li><b>${this.esc(item.label)}</b><br>${this.esc(item.text)}</li>`).join('')}</ul></details>
        ${this.references(layer.source_ids)}`;
    } else {
      const slot = data.slots.find(item => item.id === this.slot);
      body = `<div class="atlas-fields">
        ${this.select('Item slot', 'slot', data.slots.map(item => [item.id, item.label]))}
        ${this.select('Build', 'affixBuild', [['', 'All builds'], ...data.builds.map(item => [item.id, item.label])])}
        </div>`;
      body += !affixOnly && this.craftView === 'steps'
        ? this.list(slot[`${this.mode}_craft`], true)
        : this.affixes(data);
    }
    if (affixOnly) return body;
    return `${this.websiteSections('crafting')}${this.group('Crafting pages', 'craftView', [['steps', 'Crafting Steps'], ['layers', 'Special Layers']])}
      ${body}`;
  }

  pager(field, pages) {
    if (pages <= 1) return '';
    return `<div class="atlas-pager">
      <button type="button" data-atlas-page="${field}" data-delta="-1"${this[field] ? '' : ' disabled'}>Previous</button>
      <span>Page ${this[field] + 1} / ${pages}</span>
      <button type="button" data-atlas-page="${field}" data-delta="1"${this[field] + 1 < pages ? '' : ' disabled'}>Next</button>
    </div>`;
  }

  tablets() {
    const data = this.data.tablets;
    const all = data.types.flatMap(type => type.affixes);
    let body;
    if (this.tabletView === 'presets') {
      const preset = data.presets.find(item => item.id === this.preset);
      body = `${this.select('Farming preset', 'preset', data.presets.map(item => [item.id, item.label]))}
        <p>${this.esc(preset.setup)}</p>${this.list(preset[this.mode])}
        <details><summary>Priority rolls</summary>${this.list(preset.priorities.map(id => all.find(affix => affix.id === id).roll))}</details>
        <details><summary>Tablet crafting</summary>${this.list(data.crafting[this.mode], true)}
          <p class="atlas-caution">${this.esc(data.crafting.caveat)}</p></details>
        ${this.references([...new Set([...preset.source_ids, ...data.crafting.source_ids])])}`;
    } else if (this.tabletView === 'rolls') {
      const type = data.types.find(item => item.id === this.tabletType);
      const rows = type.shared_type ? data.types.find(item => item.id === type.shared_type).affixes : type.affixes;
      const pageSize = 4;
      body = `${this.select('Tablet type', 'tabletType', data.types.map(item => [item.id, item.label]))}
        <p class="atlas-muted">${this.esc(type.tip)}</p>
        <ul class="atlas-mod-list">${rows.slice(this.tabletPage * pageSize, (this.tabletPage + 1) * pageSize).map(mod =>
          `<li><b>${this.esc(mod.rank)}</b> · ${this.esc(mod.roll)}
          <small>${this.esc(mod.side)} · Max ${this.esc(mod.max_roll)}${mod.note ? ` · ${this.esc(mod.note)}` : ''}</small></li>`).join('')}</ul>
        ${this.pager('tabletPage', Math.ceil(rows.length / pageSize))}
        <p class="atlas-muted">${this.esc(data.ranking_note)}</p>${this.references(type.source_ids)}`;
    } else {
      body = `<div class="atlas-copy-list">${data.regexes.map(item =>
        `<div class="atlas-copy-row${item.danger ? ' atlas-caution' : ''}" title="${this.esc(item.tooltip)}">
          <span>${this.esc(item.label)}</span><button type="button" data-atlas-copy="${item.id}" aria-live="polite" aria-label="Copy ${this.esc(item.label)} RegEx">Copy</button>
        </div>`).join('')}</div>
        <details><summary>Show RegEx strings</summary>${data.regexes.map(item =>
          `<label class="atlas-copy-row"><span>${this.esc(item.label)}</span>
          <input readonly value="${this.esc(item.pattern)}" title="${this.esc(item.tooltip)}"></label>`).join('')}</details>
        <p class="atlas-muted">Paste the copied text into the stash search. Review highlighted items before opening a map.</p>`;
    }
    return `${this.group('Tablet pages', 'tabletView', [['presets', 'Presets'], ['rolls', 'Tablet Affixes'], ['regex', 'Stash RegEx']])}${body}`;
  }

  activeBuild() {
    const builds = this.data?.crafting.build_guides || [];
    return builds.find(item => item.id === this.guideBuild) || builds[0];
  }

  build() {
    const build = this.activeBuild();
    if (!build) return '<p>Build guides could not be loaded.</p>';
    const stages = build.stages;
    const stage = stages.find(item => item.id === this.guideStage) || stages[0];
    const recipe = build.recipes[this.guideRecipe ? Number(this.guideRecipe) : stage.recipe];
    const recipePicker = this.select('Recipe', 'guideRecipe', [['', 'Suggested upgrade'],
      ...build.recipes.map((item, i) => [String(i), item.label])]);
    const topics = [['Skills & boss rotation', 'skills'], ['Passives & Ascendancy', 'tree'],
      ['Gear & defenses', 'gear']].map(([label, key]) => `<details${this.mode === 'basis' ? ' open' : ''}>
        <summary>${label}</summary>${this.list(stage[key])}</details>`).join('');
    return `<div class="atlas-fields">
      ${this.select('Build', 'guideBuild', this.data.crafting.build_guides.map(item => [item.id, item.title]), build.id)}
      ${this.select('Build stage', 'guideStage', stages.map(item => [item.id, item.label]), stage.id)}</div>
      <h3>${this.esc(build.title)}</h3><p class="atlas-muted">${this.esc(build.author)}</p>
      <p><b>Next upgrade</b> · ${this.esc(stage.next)}</p>
      ${topics}${recipePicker}
      <p><b>${this.esc(recipe.label)}</b> · ${this.esc(recipe.quick)}</p>
      <details${this.mode === 'basis' ? ' open' : ''}><summary>Crafting steps</summary>${this.list(recipe.steps, true)}</details>
      <details><summary>Glossary</summary>${this.list(Object.entries(build.glossary || {}).map(([term, meaning]) => term + ' · ' + meaning))}</details>
      ${this.references(stage.source_ids || build.source_ids)}`;
  }

  render() {
    if (!this.root) return;
    const current = document.activeElement;
    const selector = this.root.contains(current) && current.dataset
      ? ['atlasChoice', 'atlasField', 'atlasAction', 'atlasPage'].find(key => key in current.dataset) : '';
    const scrollTop = this.root.querySelector('.atlas-panel')?.scrollTop || 0;
    const endgame = this.section === 'endgame';
    this.root.dataset.current = this.section;
    const main = this.separate ? '' : this.group('Guide', 'section', [['campaign', 'Campaign'], ['endgame', 'Endgame & Atlas']], 'atlas-top');
    let content = '';
    if (endgame && !this.data) {
      content = '<p class="atlas-status">' + (this.loadError
        ? 'Atlas data could not be loaded. <button type="button" data-atlas-action="retry">Retry</button>' : 'Loading Atlas data…') + '</p>';
    } else if (endgame) {
      const lang = document.documentElement.lang === 'de' ? 'de' : 'en';
      const tabs = this.data.website_navigation.map(({ id, title }) => [id, title[lang]]);
      if (this.content === 'all') tabs.push(['build', 'Build']);
      const nav = this.content === 'build' ? '' : this.group('Endgame & Atlas', 'tab', tabs, 'atlas-secondary');
      const panel = this.tab === 'affixes' ? this.crafting(true) : this[this.tab]();
      content = nav + `<div class="atlas-panel"><div class="atlas-content">${panel}</div></div>`;
    }
    this.root.innerHTML = main + content;
    if (endgame && this.data) this.root.querySelector('.atlas-panel').scrollTop = scrollTop;
    if (this.campaign) this.campaign.hidden = endgame;
    if (this.onSwitch) this.onSwitch(this.section);
    this.restoreFocus(current, selector);
    if (endgame && !this.data && !this.loading && !this.loadError) this.load();
  }

  restoreFocus(current, key) {
    if (!key) return;
    const focus = [...this.root.querySelectorAll('button, select')].find(element =>
      element.dataset[key] === current.dataset[key] &&
      element.dataset.value === current.dataset.value &&
      element.dataset.delta === current.dataset.delta && !element.disabled);
    focus?.focus({ preventScroll: true });
  }

  click(event) {
    const button = event.target.closest('button');
    if (!button) return;
    const {atlasChoice, value, atlasPage, delta, atlasAction, atlasCopy} = button.dataset;
    if (atlasCopy) {
      this.copy(this.data.tablets.regexes.find(item => item.id === atlasCopy), button);
      return;
    }
    if (atlasAction === 'retry') {
      this.load();
      return;
    }
    if (atlasChoice) this[atlasChoice] = value;
    else if (atlasPage) this[atlasPage] += Number(delta);
    else if (atlasAction === 'tiers') {
      this.lowerTiers = !this.lowerTiers;
      this.affixPage = 0;
    } else return;
    this.render();
  }

  change(event) {
    const field = event.target.dataset.atlasField;
    if (!field) return;
    if (field === 'guideBuild') {
      saveGuideBuild(event.target, this.activeBuild().id, this.onBuildChange);
      return;
    }
    this[field] = event.target.value;
    this.affixPage = 0;
    this.tabletPage = 0;
    this.render();
  }

  async copy(item, button) {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable');
      await navigator.clipboard.writeText(item.pattern);
    } catch (_) {
      const input = document.createElement('input');
      input.value = item.pattern;
      input.readOnly = true;
      input.setAttribute('aria-label', item.label + ' RegEx');
      button.parentElement.after(input);
      input.select();
      let copied = false;
      try { copied = document.execCommand('copy'); } catch (_) {}
      if (!copied) {
        button.textContent = 'Select & copy';
        return;
      }
      input.remove();
      button.focus({ preventScroll: true });
    }
    button.textContent = 'Copied!';
    button.dataset.copied = '';
    clearTimeout(button.copyReset);
    button.copyReset = setTimeout(() => {
      button.textContent = 'Copy';
      delete button.dataset.copied;
    }, 1600);
  }
}
