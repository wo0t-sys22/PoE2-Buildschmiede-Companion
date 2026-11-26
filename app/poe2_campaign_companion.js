async function saveGuideBuild(control, previous, apply) {
  control.disabled = true;
  try {
    const response = await fetch('/api/guide-build', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({build: control.value}),
    });
    if (!response.ok) throw new Error('Build selection failed');
    const settings = await response.json();
    apply(settings.build);
  } catch (_) {
    if (previous !== undefined) control.value = previous;
    control.title = 'Build selection could not be saved. Please try again.';
  } finally {
    control.disabled = false;
  }
}

class CampaignCompanion {
  constructor(escapeHtml, openCrafting, openView, onBuildChange) {
    this.esc = escapeHtml;
    this.openCrafting = openCrafting;
    this.openView = openView;
    this.onBuildChange = onBuildChange;
    this.data = null;
    this.view = 'quest';
    this.mode = 'basis';
    this.zone = '';
    this.level = 1;
    this.bossId = '';
    this.bossScope = '';
    this.buildId = '';
    this.stageId = '';
    this.last = '';
  }

  attach(root) {
    if (root === this.root) return;
    this.root = root;
    this.last = "";
    if (!root) return;
    this.root.addEventListener('change', event => {
      const field = event.target.dataset.companion;
      if (field === 'build') {
        saveGuideBuild(event.target, this.activeBuild().id, this.onBuildChange);
        return;
      }
      if (field === 'boss') this.bossId = event.target.value;
      else if (field === 'scope') {
        this.bossScope = event.target.value;
        this.bossId = '';
      }
      else if (field === 'stage') this.stageId = event.target.value;
      else return;
      this.render();
    });
    this.root.addEventListener('click', event => {
      const control = event.target.closest('[data-companion-open]');
      const action = control?.dataset.companionOpen;
      if (action === 'build' && !this.savingBuild) {
        this.savingBuild = true;
        saveGuideBuild(control, undefined, this.onBuildChange).finally(() => { this.savingBuild = false; });
      }
      if (action === 'crafting') this.openCrafting();
      if (action === 'boss') this.openView('boss');
      if (action === 'retry') this.load();
    });
    this.render();
  }

  current(view, zone, level, mode, buildId = '') {
    this.view = view;
    this.zone = zone;
    this.level = Math.max(1, Number(level) || 1);
    this.mode = mode;
    if (this.buildId !== buildId) {
      this.buildId = buildId;
      this.stageId = '';
    }
    this.render();
  }

  async load() {
    if (this.loading || this.data) return;
    this.loading = true;
    this.error = false;
    this.render();
    try {
      const response = await fetch('poe2_campaign_companion.json', {cache: 'no-store'});
      if (!response.ok) throw new Error('Campaign guide request failed');
      const data = await response.json();
      if (data.schema_version !== 2 || !Array.isArray(data.bosses) || !data.builds?.length) {
        throw new Error('Campaign guide data format mismatch');
      }
      this.data = data;
    } catch (_) {
      this.error = true;
    } finally {
      this.loading = false;
      this.render();
      if (this.indexTarget) this.index(this.indexTarget);
    }
  }

  bossesHere() {
    const key = campaignZoneKey(this.zone);
    return this.data?.bosses.filter(boss => key && [boss.zone, ...(boss.aliases || [])]
      .some(zone => campaignZoneKey(zone) === key)) || [];
  }

  select(label, field, options, value) {
    return `<label>${this.esc(label)} <select data-companion="${field}">${options.map(([id, name]) =>
      `<option value="${this.esc(id)}"${value === id ? ' selected' : ''}>${this.esc(name)}</option>`).join('')}</select></label>`;
  }

  links(ids) {
    return ids.map(id => this.data.sources[id]).filter(Boolean).map(source =>
      `<a href="${this.esc(source.url)}" target="_blank" rel="noopener noreferrer">${this.esc(source.label)}</a>`).join(' · ');
  }

  list(values, ordered = false) {
    const tag = ordered ? 'ol' : 'ul';
    return `<${tag}>${values.map(value => `<li>${this.esc(value)}</li>`).join('')}</${tag}>`;
  }

  bossCard(boss, full) {
    const esc = this.esc;
    const details = `${boss.prep ? `<h4>Vor dem Kampf</h4><p>${esc(boss.prep)}</p>` : ''}
      ${boss.plan ? `<h4>Kampftaktik</h4><p>${esc(boss.plan)}</p>` : ''}
      <dl class="companion-attacks">${boss.attacks.map(attack =>
      `<dt>${esc(attack.name)}</dt><dd><b class="boss-cue">Signal ·</b> ${esc(attack.tell)}<br><b class="boss-response">Reaktion ·</b> ${esc(attack.answer)}</dd>`).join('')}</dl>
      ${boss.window ? `<p><b>Konter</b> · ${esc(boss.window)}</p>` : ''}`;
    const reward = boss.rewardText || boss.reward;
    const label = ({ drop: 'Beute', quest: 'Questbelohnung', progress: 'Fortschritt', nearby: 'In der Nähe' })[boss.rewardKind] || 'Belohnung';
    return `<h3>${esc(boss.name)}</h3><small>${boss.required ? 'Pflichtboss' : 'Optionaler Boss'}</small>
      ${full ? details : `<p>${esc(boss.quick)}</p><details><summary>Angriffe &amp; Konter</summary>${details}</details>`}
      <p><b>Fundort</b> · ${esc(boss.zone)}</p>
      ${reward ? `<p><b>${label}</b> · ${esc(reward)}</p>` : ''}
      ${boss.afterFight ? `<p>${esc(boss.afterFight)}</p>` : ''}
      <details><summary>Quellen</summary><small>${this.links(boss.sources)}</small></details>`;
  }

  bossView(bosses, picked) {
    const acts = [...new Set(this.data.bosses.map(boss => boss.act))];
    const scope = this.select('Gebiet', 'scope', [['', 'Aktuelles Gebiet'], ...acts.map(act => [act, act])], this.bossScope);
    if (!picked) return scope + '<p>Wähle einen Akt, um einen Boss vorzubereiten.</p>';
    const picker = bosses.length > 1 ? this.select('Boss', 'boss', bosses.map(boss => [boss.id, boss.name]), picked.id) : '';
    return scope + picker + this.bossCard(picked, this.mode === 'basis');
  }

  activeBuild() {
    const builds = this.data?.builds || [];
    return builds.find(build => build.id === this.buildId) || builds[0];
  }

  buildView(build, stage) {
    const builds = this.data.builds;
    const picker = this.root.dataset.buildCatalog !== undefined
      ? `<div class="build-catalog" role="group" aria-label="Builds">${builds.map(item =>
        `<button type="button" data-companion-open="build" value="${this.esc(item.id)}" aria-pressed="${item.id === build.id}">
          <strong>${this.esc(item.name)}</strong><span>${this.esc(item.author)}</span></button>`).join('')}</div>`
      : this.select('Build', 'build', builds.map(item => [item.id, item.name]), build.id);
    const skills = [...(stage.editorial?.gems?.hybrid ?? []), ...(stage.skills ?? [])];
    const details = `<h4>Skills &amp; Supports</h4>${this.list(skills)}
      <h4>Tree &amp; Ascendancy</h4>${this.list(stage.passives)}
      <h4>Gear &amp; Crafting</h4>${this.list(stage.craft, true)}
      <details><summary>Begriffe erklären</summary>${this.list(Object.entries(build.glossary || {}).map(([term, meaning]) => term + ' · ' + meaning))}</details>
      <small>${this.links(stage.sources || build.sources || [])}</small>`;
    return `${picker}
      <h3>${this.esc(build.name)}</h3><small>${this.esc(build.author)}</small>
      ${this.select('Leveling', 'stage', [['', 'Automatisch'], ...build.stages.map(item => [item.id, item.label])], this.stageId)}
      <small>${this.esc(stage.label)}</small><p>${this.esc(stage.quick)}</p>
      <p><b>Als Nächstes</b> · ${this.esc(this.mode === 'basis' && stage.next ? stage.next : stage.craft[0])}</p>
      <p><button type="button" data-companion-open="crafting">Endgame-Build</button></p>
      ${this.mode === 'basis' ? details : `<details><summary>Build-Details</summary>${details}</details>`}`;
  }

  render() {
    if (!this.root) return;
    const local = this.bossesHere();
    const bosses = this.view === 'boss' && this.bossScope ? this.data.bosses.filter(boss => boss.act === this.bossScope) : local;
    const picked = bosses.find(item => item.id === this.bossId)
      || bosses.find(item => item.required) || bosses[0];
    const build = this.activeBuild();
    const stages = build?.stages || [];
    const stage = stages.find(item => item.id === this.stageId)
      || [...stages].reverse().find(item => this.level >= item.min_level) || stages[0];
    const key = JSON.stringify([this.view, this.mode, bosses.map(item => item.id), picked?.id, build?.id, stage?.id,
      this.loading, this.error, Boolean(this.data), this.stageId, this.bossScope]);
    if (key === this.last) return;
    this.last = key;
    let content = '';
    if (this.view !== 'endgame') {
      if (this.loading && ['boss', 'build'].includes(this.view)) content = '<p>Guide wird geladen …</p>';
      else if (this.error && ['boss', 'build'].includes(this.view)) content = '<button type="button" data-companion-open="retry">Guide neu laden</button>';
      else if (build && stage && this.view === 'build') content = this.buildView(build, stage);
      else if (this.data && this.view === 'boss') content = this.bossView(bosses, picked);
      else if (this.view === 'quest' && local.length) {
        const title = local.length === 1 ? local[0].name : local.length + ' Begegnungen';
        const reward = local.length === 1 && !local[0].required ? ' · ' + local[0].reward : '';
        content = `<button type="button" data-companion-open="boss">Boss · ${this.esc(title + reward)}</button>`;
      }
    }
    this.root.hidden = !content;
    this.root.innerHTML = content ? `<div class="companion-card">${content}</div>` : '';
    if (!this.data && !this.loading && !this.error) this.load();
  }

  index(target) {
    if (!target || target.dataset.loaded) return;
    this.indexTarget = target;
    if (!this.data) {
      if (!this.loading && !this.error) this.load();
      return;
    }
    target.dataset.loaded = 'true';
    const acts = new Map();
    for (const boss of this.data.bosses) {
      if (!acts.has(boss.act)) acts.set(boss.act, []);
      acts.get(boss.act).push(boss);
    }
    target.innerHTML = [...acts].map(([act, bosses]) =>
      `<details class="companion-index"><summary>${this.esc(act)}</summary>
      ${bosses.map(boss => `<details class="companion-index companion-card"><summary>${this.esc(boss.name)} · ${this.esc(boss.zone)}</summary>
      ${this.bossCard(boss, true)}</details>`).join('')}</details>`).join('');
  }
}
