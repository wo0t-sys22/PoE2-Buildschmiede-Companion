(() => {
  'use strict';
  const english = new URLSearchParams(location.search).get('lang') === 'en';
  const t = (de, en) => english ? en : de;
  const labels = {
    title:'Data exchange', intro:'Shared data for the Companion and WordPress.', current:'Active dataset',
    select:'Choose a dataset', campaign:'Campaign', bosses:'Bosses', terms:'Game terms', download:'Download JSON',
    lexicon:'Lexicon', currency:'Currencies and materials', translations:'German game translations',
    import:'Import JSON', choose:'Choose a file to preview', sample:'Examples from the file', apply:'Apply reviewed changes',
  };
  if (english) {
    document.documentElement.lang = 'en';
    document.title = 'Data exchange · Buildschmiede';
    for (const element of document.querySelectorAll('[data-i18n]')) element.textContent = labels[element.dataset.i18n];
  }
  const byId = id => document.getElementById(id);
  const select = byId('dataset'), upload = byId('upload'), download = byId('download'), apply = byId('apply');
  const status = byId('status');
  const collections = {
    'campaign.live.v2.json':['pages','towns','terms'],
    'bosses.json':['bosses','languages','sources'],
    'terms.json':['terms','areaAliases'],
    'lexicon.v1.json':['entries'],
    'currency.v1.json':['items'],
  };
  const translations = 'game-translations.de.v1.json';
  function groups(doc) {
    return select.value === translations ? Object.keys(doc).filter(key => key !== 'version') : collections[select.value];
  }
  let current = null;
  let draft = null;
  function message(value, error = false) {
    status.textContent = value;
    status.dataset.error = String(error);
  }
  function busy(locked) {
    select.disabled = upload.disabled = download.disabled = locked;
    apply.disabled = locked || !draft?.modified;
  }
  function reset() {
    draft = null;
    byId('preview').hidden = true;
    apply.disabled = true;
  }
  async function ask(method, payload) {
    const name = select.value;
    const response = await fetch(method === 'GET' ? '/api/shared-data?file=' + encodeURIComponent(name) : '/api/shared-data', {
      method, cache:'no-store',
      ...(payload ? {headers:{'Content-Type':'application/json'}, body:JSON.stringify({file:name,...payload})} : {}),
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || ('HTTP ' + response.status));
    return result;
  }
  function showCurrent(doc) {
    const name = select.value;
    const primary = name === translations ? groups(doc) : groups(doc).slice(0,1);
    const count = primary.reduce((sum, key) => sum + Object.keys(doc[key] || {}).length, 0);
    const units = {'campaign.live.v2.json':t('Gebiete','areas'), 'bosses.json':t('Bosse','bosses'), 'terms.json':t('Begriffe','terms'),
      'lexicon.v1.json':t('Artikel','articles'), 'currency.v1.json':t('Einträge','entries'), [translations]:t('Übersetzungen','translations')};
    const info = [count + ' ' + units[name], doc.source?.version, doc.source?.revision].filter(Boolean);
    byId('revision').textContent = info.join(' · ');
  }
  function entries(value) {
    const key = select.value === 'currency.v1.json' ? 'currencyId' : 'id';
    return Array.isArray(value) ? value.map(row => [row[key],row]) : Object.entries(value || {});
  }
  function examples(incoming) {
    const result = [];
    for (const group of groups(incoming)) {
      const old = new Map(entries(current?.[group]));
      for (const [id,row] of entries(incoming[group])) {
        if (JSON.stringify(old.get(id)) === JSON.stringify(row)) continue;
        result.push(group + ' / ' + id);
        if (result.length === 6) return result;
      }
    }
    return result;
  }
  async function operation(task) {
    busy(true);
    try { await task(); }
    catch (error) { message(error.message, true); }
    finally { busy(false); }
  }
  function load() {
    reset();
    upload.value = '';
    current = null;
    byId('canonical').textContent = select.value;
    byId('revision').textContent = '';
    message(t('Lade lokalen Datenstand …','Loading local data …'));
    return operation(async () => {
      current = await ask('GET');
      showCurrent(current);
      message('');
    });
  }
  select.addEventListener('change', load);
  download.addEventListener('click', () => operation(async () => {
    current = await ask('GET');
    showCurrent(current);
    const blob = new Blob([JSON.stringify(current, null, 2) + '\n'], {type:'application/json;charset=utf-8'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = select.value;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    message(t('Download gestartet.','Download started.'));
  }));
  upload.addEventListener('change', () => {
    const file = upload.files[0];
    reset();
    if (!file) { message(''); return; }
    operation(async () => {
      if (file.size > 16000000) throw Error(t('Die Datei überschreitet 16 MB.','File exceeds 16 MB.'));
      let incoming;
      try { incoming = JSON.parse((await file.text()).replace(/^\uFEFF/,'')); }
      catch { throw Error(t('Die Datei enthält kein gültiges JSON.','File does not contain valid JSON.')); }
      message(t('Prüfe Datei …','Validating file …'));
      current = await ask('GET');
      const result = await ask('POST', {document:incoming});
      const modified = result.modified ?? result.changed > 0;
      draft = {document:incoming, revision:result.revision, modified};
      const unit = result.changed === 1 ? t('Änderung','change') : t('Änderungen','changes');
      const delta = modified && !result.changed ? t('Metadaten geändert','Metadata changed') : result.changed + ' ' + unit;
      byId('delta').textContent = file.name + ' · ' + delta;
      const samples = result.changed ? examples(incoming) : [];
      const list = byId('entries');
      list.replaceChildren(...samples.map(value => { const li = document.createElement('li'); li.textContent = value; return li; }));
      byId('examples').hidden = !samples.length;
      byId('preview').hidden = false;
      message(modified ? t('Vorschau bereit.','Preview ready.') : t('Die Datei entspricht dem lokalen Stand.','File matches the local dataset.'));
    });
  });
  apply.addEventListener('click', () => operation(async () => {
    if (!draft) return;
    const reviewed = draft;
    reset();
    upload.value = '';
    await ask('POST', {document:reviewed.document,revision:reviewed.revision});
    current = await ask('GET');
    showCurrent(current);
    message(t('Änderungen gespeichert. Starte das Overlay neu, um sie zu sehen.','Changes saved. Restart the overlay to see them.'));
  }));
  load();
})();
