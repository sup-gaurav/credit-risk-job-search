/* Credit Risk Job Search System v1.0 — dashboard. Static: reads data/*.json published by the scanner. */
(() => {
'use strict';
const meta = n => document.querySelector(`meta[name="${n}"]`)?.content || '';
const OWNER = meta('crjs-owner'), REPO = meta('crjs-repo');
const PAGES = `https://${OWNER}.github.io/${REPO}/`;
const GH = `https://github.com/${OWNER}/${REPO}`;
const API = `https://api.github.com/repos/${OWNER}/${REPO}`;
const LOCAL = /(^|\.)github\.io$|^localhost$|^127\.0\.0\.1$/.test(location.hostname);
const DATA = LOCAL ? 'data/' : PAGES + 'data/';
const WORKFLOW = 'scan.yml';
const $ = (s, r = document) => r.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const safeUrl = u => /^https?:\/\//i.test(u || '') ? u : '';
const ext = (url, label, cls = '', tid = '') => safeUrl(url) ? `<a class="${cls}" href="${esc(url)}" target="_blank" rel="noopener noreferrer"${tid ? ` data-testid="${tid}"` : ''}>${label}</a>` : '';

const ICONS = {
  refresh: '<path d="M3 12a9 9 0 0 1 15.5-6.3L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.5 6.3L3 16"/><path d="M3 21v-5h5"/>',
  out: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  down: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
};
const ico = n => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n]}</svg>`;

/* localStorage is unavailable in sandboxed previews; fall back to memory. */
const store = (() => {
  const mem = {};
  let ok = false;
  try { localStorage.setItem('crjs.t', '1'); localStorage.removeItem('crjs.t'); ok = true; } catch (e) { ok = false; }
  return {
    persistent: ok,
    get(k, d) { try { const v = ok ? localStorage.getItem('crjs.' + k) : mem[k]; return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { const s = JSON.stringify(v); if (ok) { try { localStorage.setItem('crjs.' + k, s); } catch (e) { mem[k] = s; } } else mem[k] = s; },
    del(k) { if (ok) { try { localStorage.removeItem('crjs.' + k); } catch (e) { /* ignore */ } } delete mem[k]; },
  };
})();

const S = {
  tab: 'shortlist', jobs: [], status: null, cfg: null, loadError: null, loaded: false, run: null,
  f: {window: 30, bands: new Set(), category: '', city: '', platform: '', target: false, verified: false, hideDone: true, excluded: false, q: ''},
  sort: {key: 'score', dir: -1}, limit: 50,
  marks: store.get('marks', {}), checks: store.get('checks', {}),
  empF: {category: '', hiring: false},
};

/* ---------------------------------------------------------------- time + scoring (mirrors scanner/scoring.py) */
const HOUR = 3600e3;
const ageOf = j => j.posted_at ? Math.max(0, (Date.now() - Date.parse(j.posted_at)) / HOUR) : null;
// Listings that only say "1 day ago" are shown in days, the way the source states them, not as an invented hour count.
// Which searches returned a listing, by name, e.g. "found by Barclays company scan, IFRS 9 search".
const viaText = via => {
  if (!via || !via.length) return '';
  const label = {};
  (S.status?.queries || []).forEach(q => { label[q.id] = q.kind === 'company' ? `${q.label} company scan` : `${q.label} search`; });
  const names = [...new Set(via.map(v => label[v] || (v.startsWith('ats:') ? 'employer career portal' : v === 'naukri' ? 'Naukri search' : v)))];
  return `found by ${names.slice(0, 4).join(', ')}${names.length > 4 ? ` and ${names.length - 4} more` : ''}`;
};
const fmtAge = (h, precision) => h == null ? 'Date unknown' : h < 1 ? 'Under 1h ago' : (precision === 'day' && h >= 20) || h >= 48 ? `${Math.max(1, Math.floor(h / 24))}d ago` : `${Math.round(h)}h ago`;
const IST = new Intl.DateTimeFormat('en-IN', {timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false});
const fmtIST = iso => iso ? IST.format(new Date(iso)) + ' IST' : '—';
const rel = iso => { if (!iso) return 'never'; const h = (Date.now() - Date.parse(iso)) / HOUR; return h < 1 ? `${Math.max(1, Math.round(h * 60))}m ago` : h < 48 ? `${Math.round(h)}h ago` : `${Math.round(h / 24)}d ago`; };

function live(j) {
  const sc = S.cfg.scoring, w = sc.windows, age = ageOf(j);
  const fr = sc.freshness;
  let pts = fr.unknown_age_points;
  if (age != null) { const b = fr.age_points.find(b => age <= b.max_hours); pts = b ? b.points : 0; }
  let bonus = fr.unknown_applicant_points;
  if (j.applicants_n != null) { const b = fr.applicant_points.find(b => j.applicants_n <= b.max); bonus = b ? b.points : 0; }
  const fresh = Math.min(sc.weights.freshness, pts + bonus);
  const total = Math.min(j.score.cap, j.score.base + fresh);
  let excluded = j.excluded;
  if (excluded === 'below_threshold' && total >= sc.threshold) excluded = null;
  if (!excluded && total < sc.threshold) excluded = 'below_threshold';
  const band = excluded ? null : (sc.bands.find(b => total >= b.min) || {}).label || null;
  let fs;
  if (age == null) fs = {k: 'unknown', label: 'Date unknown', cls: 'warn', icon: 'alert', why: 'No source gave a usable posting time.'};
  else if (age <= w.primary_hours) {
    if (j.ats_only) fs = {k: 'portal', label: 'Portal date · verify', cls: 'warn', icon: 'alert', why: 'Seen on the employer portal only. Portal dates are often stale; confirm on LinkedIn or Naukri.'};
    else if (j.platforms.length >= 2) fs = {k: 'verified', label: 'Verified fresh', cls: 'good', icon: 'check', why: `Posted within ${w.primary_hours}h and found on ${j.platforms.length} platforms.`};
    else if (age < w.verified_single_platform_hours) fs = {k: 'verified', label: 'Verified fresh', cls: 'good', icon: 'check', why: `Single platform, timestamp under ${w.verified_single_platform_hours}h.`};
    else fs = {k: 'fresh', label: 'Fresh · one source', cls: 'info', icon: 'clock', why: `Within ${w.primary_hours}h on one platform only; not independently confirmed.`};
  } else if (age <= w.secondary_hours) fs = {k: 'recent', label: 'Recent', cls: '', icon: 'clock', why: `Between ${w.primary_hours}h and ${w.secondary_hours}h old.`};
  else fs = {k: 'older', label: 'Older', cls: '', icon: 'clock', why: `More than ${w.secondary_hours}h old.`};
  return {age, fresh, total, excluded, band, fs};
}
const bandCls = b => b === 'Tier 1' ? 't1' : b === 'Tier 2' ? 't2' : b === 'Tier 3' ? 't3' : 'x';
const scoreBox = (j, L) => `<span class="score ${bandCls(L.band)}" title="${esc(L.band || 'Filtered out')}">${L.total}<small>${L.band ? L.band.replace('Tier ', 'T') : 'OUT'}</small></span>`;
const applyUrl = j => safeUrl(j.apply_url) || safeUrl((j.sources.find(s => s.platform === 'linkedin') || j.sources[0] || {}).url);
const PLATFORM = {linkedin: 'LinkedIn', naukri: 'Naukri', workday: 'Workday', greenhouse: 'Greenhouse', lever: 'Lever', smartrecruiters: 'SmartRecruiters', oracle: 'Oracle HCM'};
const pname = p => PLATFORM[p] || p;
const exLabel = id => id === 'irrelevant' ? 'Not relevant' : ((S.cfg.scoring.exclusions.find(x => x.id === id) || {}).label || id);
const emp = id => S.cfg.employers.find(e => e.id === id);

/* ---------------------------------------------------------------- deep links (Section 3.2) */
const liUrl = (keywords, seconds = 86400, location = 'India', levels = '4,5', ids = null) =>
  'https://www.linkedin.com/jobs/search/?' + new URLSearchParams({keywords, location, ...(ids && ids.length ? {f_C: ids.join(',')} : {}), f_TPR: 'r' + seconds, sortBy: 'DD', ...(levels ? {f_E: levels} : {})}).toString();
const liCompanyJobs = slug => `https://www.linkedin.com/company/${encodeURIComponent(slug)}/jobs/`;
function nkUrl({k, l, experience, ctc}) {
  let slug = k.toLowerCase().replace(/&/g, 'and').replace(/'/g, '').trim().split(/\s+/).join('-') + '-jobs';
  if (l) slug += '-in-' + l.toLowerCase().trim().split(/\s+/).join('-');
  let u = `https://www.naukri.com/${encodeURIComponent(slug)}?k=${encodeURIComponent(k)}`;
  if (l) u += `&l=${encodeURIComponent(l)}`;
  if (experience != null) u += `&experience=${experience}`;
  (ctc || []).forEach(c => { u += `&ctcFilter=${c}`; });
  return u + '&jobAge=1';
}

/* ---------------------------------------------------------------- data */
async function getJSON(name) {
  const r = await fetch(`${DATA}${name}?t=${Date.now()}`, {cache: 'no-store'});
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
  return r.json();
}
async function load(quiet) {
  try {
    const [cfg, status, jobs] = await Promise.all([getJSON('config.json'), getJSON('status.json'), getJSON('jobs.json')]);
    const changed = !S.status || S.status.finished !== status.finished || S.status.rescored_at !== status.rescored_at;
    S.cfg = cfg; S.status = status; S.jobs = jobs.jobs || []; S.loadError = null; S.loaded = true;
    if (!quiet && S.status.secondary_window_used && !S._windowSet) { S.f.window = 72; }
    S._windowSet = true;
    return changed;
  } catch (e) {
    S.loadError = e.message; S.loaded = true; return false;
  }
}
async function checkRun() {
  try {
    const r = await fetch(`${API}/actions/workflows/${WORKFLOW}/runs?per_page=1`, {headers: {Accept: 'application/vnd.github+json'}});
    if (!r.ok) return;
    const run = (await r.json()).workflow_runs?.[0];
    const was = S.run && S.run.status !== 'completed';
    S.run = run || null;
    renderScanState();
    if (run && run.status !== 'completed') { clearTimeout(S._poll); S._poll = setTimeout(checkRun, 60000); }
    else if (was) { const changed = await load(true); render(); toast(changed ? 'Scan finished. Results updated.' : 'Scan finished. Publishing results…'); if (!changed) setTimeout(async () => { await load(true); render(); }, 90000); }
  } catch (e) { /* rate limited or offline: the page still works */ }
}

/* ---------------------------------------------------------------- header */
function nextRun() {
  const s = S.cfg?.search?.schedule; if (!s) return null;
  const now = new Date(), utcMin = (s.hour_ist * 60 + s.minute_ist - 330 + 1440) % 1440;
  const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), Math.floor(utcMin / 60), utcMin % 60));
  if (d <= now) d.setUTCDate(d.getUTCDate() + 1);
  return d;
}
function renderScanState() {
  const el = $('#scan-state'), st = S.status, run = S.run;
  let cls = '', html = '';
  if (run && run.status !== 'completed') {
    const mins = Math.max(0, Math.round((Date.now() - Date.parse(run.run_started_at || run.created_at)) / 60000));
    cls = 'run'; html = `Scan running · ${mins}m · ${ext(run.html_url, 'view', '', 'link-run')}`;
  } else if (!st) html = 'Loading…';
  else if (st.state === 'never_run') { cls = 'warn'; html = 'No scan yet'; }
  else {
    const li = st.sources?.linkedin || {}, gaps = li.state !== 'ok' || (run && run.conclusion === 'failure');
    cls = gaps ? 'warn' : 'ok';
    const nx = nextRun();
    html = `<span title="${esc(fmtIST(st.finished))}">Updated ${esc(rel(st.finished))}</span><span class="hide-sm"> · next ${esc(nx ? fmtIST(nx.toISOString()) : '—')}</span>${run && run.conclusion === 'failure' ? ' · ' + ext(run.html_url, 'last run failed') : ''}`;
  }
  el.className = 'scan-state ' + cls;
  el.innerHTML = `<span class="dot"></span><span>${html}</span>`;
  const b = $('#btn-refresh'), running = run && run.status !== 'completed';
  b.classList.toggle('spin', !!running);
  b.lastElementChild.textContent = running ? 'Scanning' : 'Refresh';
}
function renderTabs() {
  const fresh = S.loaded && S.cfg ? shortlistBase().filter(x => x.L.age != null && x.L.age <= S.cfg.scoring.windows.primary_hours && !x.L.excluded).length : null;
  const tabs = [['shortlist', 'Shortlist', fresh], ['employers', 'Employers', S.cfg ? S.cfg.employers.length : null], ['launcher', 'Search launcher'], ['coverage', 'Coverage'], ['logic', 'Logic']];
  $('#tabs').innerHTML = tabs.map(([id, label, n]) => `<button class="tab" role="tab" aria-selected="${S.tab === id}" data-tab="${id}" data-testid="tab-${id}">${label}${n != null ? `<span class="n">${n}</span>` : ''}</button>`).join('');
}

/* ---------------------------------------------------------------- shortlist */
function shortlistBase() { return S.jobs.filter(j => !j.closed).map(j => ({j, L: live(j)})); }
function filtered() {
  const f = S.f, q = f.q.trim().toLowerCase();
  let rows = shortlistBase().filter(({j, L}) => {
    if (!f.excluded && L.excluded) return false;
    if (f.window && (L.age == null || L.age > f.window)) return false;
    if (f.bands.size && !f.bands.has(L.band)) return false;
    if (f.category && j.category !== f.category) return false;
    if (f.city && !(j.cities || []).includes(f.city) && j.city !== f.city) return false;
    if (f.platform && !j.platforms.includes(f.platform)) return false;
    if (f.target && !j.employer_id) return false;
    if (f.verified && L.fs.k !== 'verified') return false;
    if (f.hideDone && ['applied', 'skip'].includes(S.marks[j.id])) return false;
    if (q && !(`${j.title} ${j.company} ${j.location} ${Object.values(j.matched || {}).flat().join(' ')}`.toLowerCase().includes(q))) return false;
    return true;
  });
  const {key, dir} = S.sort;
  const val = {score: r => r.L.total, posted: r => -(r.L.age ?? 1e9), company: r => r.j.company.toLowerCase(), applicants: r => -(r.j.applicants_n ?? 1e9)}[key];
  rows.sort((a, b) => (a.L.excluded ? 1 : 0) - (b.L.excluded ? 1 : 0) || (val(a) < val(b) ? -1 : val(a) > val(b) ? 1 : 0) * dir || (a.L.age ?? 1e9) - (b.L.age ?? 1e9));
  return rows;
}
const freshTag = L => `<span class="tag ${L.fs.cls}" title="${esc(L.fs.why)}">${ico(L.fs.icon)}${esc(L.fs.label)}</span>`;
const srcTags = j => j.platforms.map(p => `<span class="tag">${esc(pname(p))}</span>`).join('');
const markSel = j => `<select class="mark" data-mark="${esc(j.id)}" data-testid="select-mark-${esc(j.id)}" aria-label="Tracking status for ${esc(j.title)}">${[['', 'New'], ['saved', 'Saved'], ['applied', 'Applied'], ['skip', 'Skip']].map(([v, l]) => `<option value="${v}"${(S.marks[j.id] || '') === v ? ' selected' : ''}>${l}</option>`).join('')}</select>`;

function viewShortlist() {
  const st = S.status, sc = S.cfg.scoring, w = sc.windows;
  if (st.state === 'never_run') {
    return `<section class="view"><div class="panel empty" data-testid="empty-never-run"><h3>No scan has run yet</h3><p>The first scan runs at 9:00 AM IST, or start one now. It takes about 30 to 60 minutes.</p><button class="btn primary" data-act="refresh" data-testid="button-first-scan">${ico('refresh')} Run first scan</button></div></section>`;
  }
  const base = shortlistBase().filter(x => !x.L.excluded);
  const in30 = base.filter(x => x.L.age != null && x.L.age <= w.primary_hours), in72 = base.filter(x => x.L.age != null && x.L.age <= w.secondary_hours);
  const li = st.sources?.linkedin || {}, at = st.sources?.ats || {};
  const kpis = [
    ['lead', in30.length, `Fresh roles, last ${w.primary_hours}h`, `${in72.length} within ${w.secondary_hours}h`],
    ['', in30.filter(x => x.L.fs.k === 'verified').length, 'Verified fresh', '2+ platforms or under 12h'],
    ['', in30.filter(x => x.L.band === 'Tier 1').length, 'Tier 1', 'Score 90+'],
    ['', in30.filter(x => x.L.band === 'Tier 2').length, 'Tier 2', 'Score 75–89'],
    ['', new Set(in72.map(x => x.j.employer_id).filter(Boolean)).size, 'Target employers hiring', `of ${S.cfg.employers.filter(e => !e.same_as).length} tracked, ${w.secondary_hours}h`],
    ['', `${li.ok ?? 0}/${li.queries ?? 0}`, 'LinkedIn queries answered', `${at.ok ?? 0}/${at.configured ?? 0} career portals`],
  ];
  const rows = filtered();
  const win = S.f.window || 1e9;
  const top = shortlistBase().filter(x => !x.L.excluded && x.L.age != null && x.L.age <= win && !['applied', 'skip'].includes(S.marks[x.j.id]))
    .sort((a, b) => b.L.total - a.L.total || a.L.age - b.L.age).slice(0, 10);
  const notes = [];
  if (st.secondary_window_used) notes.push(`<div class="note" data-testid="note-secondary">${ico('info')}<span>Fewer than ${w.secondary_trigger_below} roles cleared the threshold in ${w.primary_hours}h, so the scan added the ${w.secondary_hours}h window.</span></div>`);
  if (li.state && li.state !== 'ok') notes.push(`<div class="note warn" data-testid="note-coverage">${ico('alert')}<span>LinkedIn answered ${li.ok ?? 0} of ${li.queries ?? 0} queries${li.aborted ? ' before rate limiting stopped the scan' : ''}. Missing queries are gaps, not zero vacancies. <a href="#main" data-goto="coverage">See coverage</a></span></div>`);
  const cities = [...new Set(S.jobs.flatMap(j => j.cities?.length ? j.cities : [j.city]))].filter(Boolean).sort();
  const plats = [...new Set(S.jobs.flatMap(j => j.platforms))].sort();
  const f = S.f;
  const sortBtn = (k, label) => `<button data-sort="${k}" data-testid="sort-${k}">${label}${S.sort.key === k ? (S.sort.dir < 0 ? ' ↓' : ' ↑') : ''}</button>`;
  const shown = rows.slice(0, S.limit);
  return `<section class="view">
  <div class="kpis">${kpis.map(([c, v, l, d], i) => `<div class="kpi ${c}" data-testid="kpi-${i}"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div><div class="d">${esc(d)}</div></div>`).join('')}</div>
  ${notes.join('')}
  <div class="head"><h2 class="h2">Top ${top.length || 10} to apply</h2><span class="sub">${f.window ? `Last ${f.window >= 168 ? '7 days' : f.window + 'h'}` : 'All dates'}, ranked by score then freshness</span></div>
  ${top.length ? `<ol class="top10">${top.map(({j, L}, i) => `<li class="pick" data-testid="pick-${i + 1}">
      <span class="rank">${i + 1}</span>
      <div><button class="t" data-open="${esc(j.id)}" data-testid="button-open-pick-${i + 1}">${esc(j.title)}</button><div class="m"><b>${esc(j.company)}</b> · ${esc(j.city)} · ${esc(fmtAge(L.age, j.precision))}${j.applicants_text ? ' · ' + esc(j.applicants_text) : ''}</div><div class="tags" style="margin-top:6px">${freshTag(L)}${j.tier ? `<span class="tag">${esc(j.tier)}</span>` : ''}</div></div>
      <div class="side">${scoreBox(j, L)}${ext(applyUrl(j), 'Apply ' + ico('out'), 'btn sm primary', `link-apply-pick-${i + 1}`)}</div></li>`).join('')}</ol>`
    : `<div class="panel empty" data-testid="empty-top"><h3>Nothing cleared the threshold in this window</h3><p>Widen the window, or check coverage before treating this as a quiet day.</p></div>`}
  <div class="head"><h2 class="h2">All roles</h2><div class="links"><span class="sub" data-testid="text-count">${rows.length} shown</span><button class="btn sm" data-act="csv" data-testid="button-csv">${ico('down')} CSV</button></div></div>
  <div class="filters" role="group" aria-label="Filters">
    <div class="seg" role="group" aria-label="Posting window">${[[30, '30h'], [72, '72h'], [168, '7d'], [0, 'All']].map(([v, l]) => `<button aria-pressed="${f.window === v}" data-window="${v}" data-testid="filter-window-${v}">${l}</button>`).join('')}</div>
    <div class="chips" role="group" aria-label="Tier">${sc.bands.map(b => `<button class="chip" aria-pressed="${f.bands.has(b.label)}" data-band="${esc(b.label)}" data-testid="filter-${b.label.replace(' ', '').toLowerCase()}">${esc(b.label)}</button>`).join('')}</div>
    <select data-f="category" data-testid="filter-category" aria-label="Employer category"><option value="">All categories</option>${Object.entries(S.cfg.categories).map(([k, v]) => `<option value="${k}"${f.category === k ? ' selected' : ''}>${k} · ${esc(v)}</option>`).join('')}</select>
    <select data-f="city" data-testid="filter-city" aria-label="City"><option value="">All cities</option>${cities.map(c => `<option${f.city === c ? ' selected' : ''}>${esc(c)}</option>`).join('')}</select>
    <select data-f="platform" data-testid="filter-platform" aria-label="Platform"><option value="">All platforms</option>${plats.map(p => `<option value="${esc(p)}"${f.platform === p ? ' selected' : ''}>${esc(pname(p))}</option>`).join('')}</select>
    <div class="grow"><label class="sr" for="q">Search roles</label><input type="search" id="q" data-testid="input-search" placeholder="Search title, company, skill" value="${esc(f.q)}"></div>
    <label class="check"><input type="checkbox" data-t="target" data-testid="toggle-target"${f.target ? ' checked' : ''}>Target employers</label>
    <label class="check"><input type="checkbox" data-t="verified" data-testid="toggle-verified"${f.verified ? ' checked' : ''}>Verified fresh</label>
    <label class="check"><input type="checkbox" data-t="hideDone" data-testid="toggle-hide-done"${f.hideDone ? ' checked' : ''}>Hide applied and skipped</label>
    <label class="check"><input type="checkbox" data-t="excluded" data-testid="toggle-excluded"${f.excluded ? ' checked' : ''}>Show filtered-out</label>
  </div>
  ${rows.length ? `<div class="tablewrap"><table data-testid="table-roles"><thead><tr><th>${sortBtn('score', 'Score')}</th><th>Role</th><th>Location</th><th>${sortBtn('posted', 'Posted')}</th><th>${sortBtn('applicants', 'Applicants')}</th><th>Found on</th><th>Track</th><th><span class="sr">Apply</span></th></tr></thead><tbody>
    ${shown.map(({j, L}) => `<tr class="rowlink${L.excluded ? ' dim' : ''}" tabindex="0" data-open="${esc(j.id)}" data-testid="row-role-${esc(j.id)}">
      <td>${scoreBox(j, L)}</td>
      <td class="role"><div class="t">${esc(j.title)}</div><div class="c">${esc(j.company)}${j.tier ? ` <span class="tag">${esc(j.tier)}</span>` : ''}${L.excluded ? ` <span class="tag bad">${esc(exLabel(L.excluded))}</span>` : ''}${j.score.title_only ? ' <span class="tag" title="Description not read; skills estimated from the title">Title only</span>' : ''}</div></td>
      <td>${esc(j.city)}</td>
      <td class="nowrap">${esc(fmtAge(L.age, j.precision))}<div style="margin-top:4px">${freshTag(L)}</div></td>
      <td class="muted">${esc(j.applicants_text || j.badge || '—')}</td>
      <td><div class="tags">${srcTags(j)}</div></td>
      <td>${markSel(j)}</td>
      <td>${ext(applyUrl(j), 'Apply ' + ico('out'), 'btn sm', `link-apply-${esc(j.id)}`)}</td></tr>`).join('')}
    </tbody></table></div>${rows.length > shown.length ? `<div class="more"><button class="btn" data-act="more" data-testid="button-more">Show ${Math.min(50, rows.length - shown.length)} more</button></div>` : ''}`
    : `<div class="panel empty" data-testid="empty-roles"><h3>No roles match these filters</h3><p>Try a wider window or clear a filter.</p><button class="btn" data-act="clear" data-testid="button-clear">Clear filters</button></div>`}
  </section>`;
}

function openDrawer(id) {
  const j = S.jobs.find(x => x.id === id); if (!j) return;
  const L = live(j), w = S.cfg.scoring.weights, s = j.score, e = j.employer_id && emp(j.employer_id);
  const parts = [['Role fit', s.role, w.role, s.role_class], ['Skills match', s.skills, w.skills, s.title_only ? 'Estimated from title; description not read' : ''], ['Employer', s.employer, w.employer, e ? `${S.cfg.categories[e.category]} · ${S.cfg.tiers[e.tier]}` : 'Outside the target list'], ['Seniority', s.seniority, w.seniority, s.seniority_label], ['Location', s.location, w.location, j.city], ['Freshness', L.fresh, w.freshness, `${fmtAge(L.age)}${j.applicants_text ? ', ' + j.applicants_text : ''}`]];
  const kw = [...(j.matched?.core || []), ...(j.matched?.techniques || []), ...(j.matched?.stack || [])];
  const d = $('#drawer');
  d.innerHTML = `<div class="in" data-testid="drawer-role">
    <div class="dhead">${scoreBox(j, L)}<div><h2>${esc(j.title)}</h2><div class="sub">${esc(j.company)}${j.company_raw ? ` (${esc(j.company_raw)})` : ''} · ${esc(j.location || j.city)}</div></div><button class="btn ghost icon x" data-act="close-drawer" data-testid="button-close-drawer" aria-label="Close">${ico('x')}</button></div>
    <div class="links">${ext(applyUrl(j), 'Apply ' + ico('out'), 'btn primary', 'link-apply-drawer')}${j.sources.map(x => ext(x.url, esc(pname(x.platform)) + ' listing ' + ico('out'), 'btn')).join('')}${markSel(j)}</div>
    ${L.excluded ? `<div class="note warn">${ico('alert')}<span>Filtered out: ${esc(exLabel(L.excluded))}.</span></div>` : ''}
    <div><h3 class="h3">Score ${L.total} of 100${s.base + L.fresh > s.cap ? ` · capped at ${s.cap}` : ''}</h3>
      <div class="bars" style="margin-top:12px">${parts.map(([n, v, m, note]) => `<span>${n}</span><div><div class="bar"><i style="width:${Math.round(100 * v / m)}%"></i></div>${note ? `<div class="sub" style="font-size:12px;margin-top:2px">${esc(note)}</div>` : ''}</div><span class="nowrap"><b>${v}</b> / ${m}</span>`).join('')}</div></div>
    <div><h3 class="h3">Freshness evidence</h3><dl class="kv" style="margin-top:12px">
      <dt>Status</dt><dd>${freshTag(L)} <span class="sub">${esc(L.fs.why)}</span></dd>
      <dt>Posted</dt><dd>${j.posted_at ? `${esc(fmtIST(j.posted_at))} <span class="sub">(${j.precision === 'hour' ? 'to the hour' : j.precision === 'day' ? 'day-level estimate' : 'coarse estimate'}, from ${esc(pname(j.posted_source))}: “${esc(j.posted_text || '')}”)</span>` : 'Unknown'}</dd>
      <dt>First seen</dt><dd>${esc(fmtIST(j.first_seen))} by this scanner${j.in_latest_scan ? '' : ' · not returned by the latest scan'}</dd>
      ${j.reposted ? '<dt>Repost</dt><dd>The listing shows a repost or a newer date than first recorded.</dd>' : ''}
      <dt>Sources</dt><dd>${j.sources.map(x => `${esc(pname(x.platform))} “${esc(x.posted_text || '—')}” <span class="sub">${esc(viaText(x.via))}</span>`).join('<br>')}</dd>
      ${j.seniority_level ? `<dt>LinkedIn level</dt><dd>${esc(j.seniority_level)}${j.employment_type ? ' · ' + esc(j.employment_type) : ''}</dd>` : ''}
    </dl></div>
    ${kw.length ? `<div><h3 class="h3">Matched in the posting</h3><div class="tags" style="margin-top:12px">${kw.map(k => `<span class="tag good">${esc(k)}</span>`).join('')}</div></div>` : ''}
    ${j.excerpt ? `<div><h3 class="h3">Description excerpt</h3><p class="excerpt" style="margin-top:12px">${esc(j.excerpt)}${j.desc_chars > j.excerpt.length ? '…' : ''}</p></div>` : ''}
  </div>`;
  if (!d.open) d.showModal();
}

/* ---------------------------------------------------------------- employers */
function viewEmployers() {
  const w = S.cfg.scoring.windows, base = shortlistBase().filter(x => !x.L.excluded && x.L.age != null);
  const count = (id, h) => base.filter(x => x.j.employer_id === id && x.L.age <= h).length;
  const ats = S.status.ats || {}, f = S.empF;
  const never = S.status.state === 'never_run';
  const portal = e => {
    if (!e.ats_type) return '<span class="tag" title="No public job feed configured; use the careers link">Manual</span>';
    const a = ats[e.id];
    if (!a) return `<span class="tag">${esc(pname(e.ats_type))} · pending</span>`;
    return a.state === 'ok' ? `<span class="tag good" title="${esc(pname(e.ats_type))} feed answered">${ico('check')}${a.returned} relevant</span>` : `<span class="tag warn" title="${esc(a.error || a.state)}">${ico('alert')}No answer</span>`;
  };
  let body = '';
  for (const [cat, catName] of Object.entries(S.cfg.categories)) {
    if (f.category && f.category !== cat) continue;
    const list = S.cfg.employers.filter(e => e.category === cat && (!f.hiring || count(e.same_as || e.id, w.secondary_hours) > 0));
    if (!list.length) continue;
    body += `<tr class="grouphead"><td colspan="7">${cat} · ${esc(catName)}<span>${list.length} employers</span></td></tr>`;
    body += list.map(e => {
      const id = e.same_as || e.id, a = count(id, w.primary_hours), b = count(id, w.secondary_hours);
      return `<tr data-testid="row-employer-${esc(e.id)}"><td class="muted num">${e.n}</td>
        <td class="role"><div class="t">${esc(e.name)}${e.conditional ? ' <span class="tag" title="Listed in the master prompt as conditional on India presence or hiring">Conditional</span>' : ''}</div><div class="c">${esc(e.focus)}${e.note ? ' · ' + esc(e.note) : ''}</div></td>
        <td><span class="tag" title="${esc(S.cfg.tiers[e.tier])}">${esc(e.tier)}</span></td>
        <td class="num">${never ? '—' : a ? `<b>${a}</b>` : '<span class="muted">0</span>'}</td><td class="num">${never ? '—' : b ? `<b>${b}</b>` : '<span class="muted">0</span>'}</td>
        <td>${e.same_as ? '<span class="muted">See Citi</span>' : portal(e)}</td>
        <td><div class="links">${ext(liUrl(e.linkedin_keywords, 86400, 'India', '4,5', e.linkedin_ids), 'LinkedIn 24h', 'btn sm', `link-li-${esc(e.id)}`)}${e.linkedin_slug ? ext(liCompanyJobs(e.linkedin_slug), 'Company jobs', 'btn sm') : ''}${ext(nkUrl({k: `${e.query} credit risk`}), 'Naukri today', 'btn sm', `link-nk-${esc(e.id)}`)}${ext(e.careers_url, 'Careers', 'btn sm')}</div></td></tr>`;
    }).join('');
  }
  return `<section class="view">
    <div class="head"><h2 class="h2">Target employer universe</h2><span class="sub">${S.cfg.employers.length} entries across ${Object.keys(S.cfg.categories).length} categories</span></div>
    <div class="filters"><div class="chips" role="group" aria-label="Category"><button class="chip" aria-pressed="${!f.category}" data-ecat="">All</button>${Object.keys(S.cfg.categories).map(k => `<button class="chip" aria-pressed="${f.category === k}" data-ecat="${k}" data-testid="filter-ecat-${k}" title="${esc(S.cfg.categories[k])}">${k}</button>`).join('')}</div>
      <label class="check"><input type="checkbox" data-et="hiring" data-testid="toggle-hiring"${f.hiring ? ' checked' : ''}>With roles in ${w.secondary_hours}h</label></div>
    <div class="tablewrap"><table data-testid="table-employers"><thead><tr><th class="num">#</th><th>Employer</th><th>Tier</th><th class="num">${w.primary_hours}h</th><th class="num">${w.secondary_hours}h</th><th>Career portal</th><th>Open a fresh search</th></tr></thead><tbody>${body || '<tr><td colspan="7" class="empty">No employers match.</td></tr>'}</tbody></table></div>
  </section>`;
}

/* ---------------------------------------------------------------- launcher */
function viewLauncher() {
  const se = S.cfg.search, qs = S.status.queries || [];
  const res = id => { const hit = qs.filter(q => q.id === id || q.id.startsWith(id)); if (!hit.length) return '<span class="muted">—</span>'; const n = Math.max(...hit.map(q => q.returned || 0)); const bad = hit.some(q => q.state !== 'ok'); return bad ? `<span class="tag warn">${ico('alert')}Gap</span>` : `${n}${hit.some(q => q.capped) ? '+' : ''}`; };
  const nk = S.status.sources?.naukri;
  const due = p => { const last = S.checks[p.id]; if (!last) return '<span class="tag warn">Due</span>'; const days = (Date.now() - Date.parse(last)) / 864e5; return days >= p.cadence_days ? `<span class="tag warn">Due · last ${esc(rel(last))}</span>` : `<span class="tag good">${ico('check')}Checked ${esc(rel(last))}</span>`; };
  return `<section class="view">
    <div class="head"><h2 class="h2">LinkedIn skill searches</h2><span class="sub">Method B · run automatically each scan</span></div>
    <div class="tablewrap"><table data-testid="table-skill-queries"><thead><tr><th>ID</th><th>Search</th><th>Query</th><th class="num">Last scan</th><th>Open on LinkedIn</th></tr></thead><tbody>
      ${se.linkedin.skill_queries.map(q => `<tr><td class="muted">${q.id}</td><td><b>${esc(q.label)}</b><div class="sub">${esc(q.set)}${q.locations ? ' · ' + q.locations.map(l => esc(l.split(',')[0])).join(', ') : ''}</div></td><td class="mono">${esc(q.keywords)}</td><td class="num">${res(q.id)}</td>
        <td><div class="links">${(q.locations || ['India']).map(l => ext(liUrl(q.keywords, 86400, l), q.locations ? esc(l.split(',')[0]) + ' 24h' : 'Past 24h', 'btn sm', `link-skill-${q.id}`)).join('')}${ext(liUrl(q.keywords, 108000, 'India', ''), '30h, all levels', 'btn sm')}</div></td></tr>`).join('')}
    </tbody></table></div>
    <div class="head"><h2 class="h2">Naukri.com searches</h2><span class="sub">Posted today · opens in a new tab</span></div>
    <div class="note${nk && nk.state === 'ok' ? '' : ' warn'}" data-testid="note-naukri">${ico(nk && nk.state === 'ok' ? 'info' : 'alert')}<span>${nk && nk.state === 'ok' ? `Naukri answered the last scan with ${nk.returned} listings.` : 'Naukri asks automated clients for an interactive check, so the scanner does not read it. These links run each search for you with the freshness filter applied. Each employer row has its own Naukri link too.'}</span></div>
    <div class="tablewrap"><table data-testid="table-naukri"><thead><tr><th>Search</th><th>Keywords</th><th>Open</th></tr></thead><tbody>
      ${se.naukri.skill_searches.map((q, i) => `<tr><td><b>${esc(q.label)}</b></td><td class="mono">${esc(q.k)}${q.l ? ' · ' + esc(q.l) : ''}${q.experience != null ? ` · ${q.experience}+ yrs` : ''}</td><td>${ext(nkUrl(q), 'Posted today', 'btn sm', `link-naukri-${i}`)}</td></tr>`).join('')}
    </tbody></table></div>
    <div class="head"><h2 class="h2">Weekly and monthly platforms</h2><span class="sub">Manual checks${store.persistent ? '' : ' · tracking resets when this page closes'}</span></div>
    <div class="tablewrap"><table data-testid="table-manual"><thead><tr><th>Platform</th><th>Cadence</th><th>Search</th><th>Status</th><th>Open</th></tr></thead><tbody>
      ${se.manual_platforms.map(p => `<tr><td><b>${esc(p.name)}</b><div class="sub">${esc(p.why)}</div></td><td class="nowrap">${esc(p.cadence)}</td><td class="sub">${esc(p.params)}</td><td>${due(p)}</td>
        <td><div class="links">${p.links.map(l => ext(l.url, esc(l.label), 'btn sm')).join('')}<button class="btn sm" data-check="${esc(p.id)}" data-testid="button-check-${esc(p.id)}">Mark checked</button></div></td></tr>`).join('')}
    </tbody></table></div>
  </section>`;
}

/* ---------------------------------------------------------------- coverage */
const stateTag = s => { const good = s === 'ok', warn = ['partial', 'manual', 'running', 'budget_exhausted', 'skipped_budget'].includes(s); return `<span class="tag ${good ? 'good' : warn ? 'warn' : 'bad'}">${ico(good ? 'check' : 'alert')}${esc(String(s).replace(/_/g, ' '))}</span>`; };
function viewCoverage() {
  const st = S.status;
  if (st.state === 'never_run') return `<section class="view"><div class="panel empty"><h3>No scan has run yet</h3><p>Coverage appears after the first scan.</p></div></section>`;
  const li = st.sources?.linkedin || {}, at = st.sources?.ats || {}, nk = st.sources?.naukri || {}, d = li.details || {}, fn = st.funnel || {};
  const phaseDetail = p => { const skip = new Set(['id', 'name', 'state', 'started', 'seconds']); return Object.entries(p).filter(([k]) => !skip.has(k)).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${typeof v === 'object' ? Object.entries(v).map(([a, b]) => `${a} ${b}`).join(', ') : v}`).join(' · '); };
  const qs = st.queries || [];
  const qTable = list => `<div class="tablewrap"><table><thead><tr><th>ID</th><th>Query</th><th>Window</th><th>State</th><th class="num">Returned</th><th class="num">Pages</th></tr></thead><tbody>${list.map(q => `<tr><td class="muted">${esc(q.id)}</td><td><b>${esc(q.label)}</b>${q.mode === 'keyword' ? ' <span class="tag warn" title="LinkedIn did not return a company id, so the employer name is matched as a keyword and other employers can appear">Keyword match</span>' : ''}<div class="mono">${q.company_names ? 'company: ' + esc(q.company_names.join(', ')) + ' · ' : ''}${esc(q.keywords)} · ${esc(q.location)}</div></td><td>${q.window_hours}h</td><td>${stateTag(q.state)}</td><td class="num">${q.returned ?? 0}${q.capped ? '+' : ''}</td><td class="num">${q.pages ?? 0}</td></tr>`).join('')}</tbody></table></div>`;
  const cq = qs.filter(q => q.kind === 'company'), sq = qs.filter(q => q.kind === 'skill');
  const gaps = l => l.filter(q => q.state !== 'ok').length;
  const capN = l => l.filter(q => q.capped).length;
  const hist = (st.history || []).slice(-14).reverse();
  return `<section class="view">
    <div class="head"><h2 class="h2">Last scan</h2><span class="sub">${esc(fmtIST(st.started))} · ${Math.round((st.duration_seconds || 0) / 60)} min · trigger: ${esc(st.trigger || '—')}${st.run_url ? ' · ' + ext(st.run_url, 'run log') : ''}</span></div>
    <div class="kpis">
      <div class="kpi"><div class="v">${li.ok ?? 0}/${li.queries ?? 0}</div><div class="l">LinkedIn queries</div><div class="d">${li.throttle_events || 0} rate-limit events${li.aborted ? ', stopped early' : ''}</div></div>
      <div class="kpi"><div class="v">${d.read ?? 0}</div><div class="l">Descriptions read</div><div class="d">${d.unread ?? 0} promising roles unread</div></div>
      <div class="kpi"><div class="v">${at.ok ?? 0}/${at.configured ?? 0}</div><div class="l">Career portals</div><div class="d">Public job feeds answering</div></div>
      <div class="kpi"><div class="v">${nk.state === 'ok' ? nk.returned : 'Manual'}</div><div class="l">Naukri.com</div><div class="d">${nk.state === 'ok' ? 'Listings read' : 'Interactive check required'}</div></div>
      <div class="kpi"><div class="v">${fn.observations ?? 0}</div><div class="l">Listings seen</div><div class="d">Before deduplication</div></div>
      <div class="kpi"><div class="v">${fn.qualified_primary ?? 0}</div><div class="l">Cleared threshold, ${S.cfg.scoring.windows.primary_hours}h</div><div class="d">${fn.qualified_secondary ?? 0} within ${S.cfg.scoring.windows.secondary_hours}h</div></div>
    </div>
    <div class="note">${ico('info')}<span>${esc(st.coverage_note || '')}</span></div>
    <div class="grid2">
      <div class="panel pad"><h3 class="h3">Phases</h3>${(st.phases || []).map(p => `<div class="phase"><span class="n">${esc(p.id)}</span><div><b>${esc(p.name)}</b><div class="d">${esc(phaseDetail(p))}</div></div><div class="nowrap">${stateTag(p.state)} <span class="muted">${p.seconds != null ? Math.round(p.seconds) + 's' : ''}</span></div></div>`).join('')}</div>
      <div class="panel pad"><h3 class="h3">Run history</h3>${hist.length ? `<div class="scrollx"><table style="margin-top:8px"><thead><tr><th>Scan</th><th class="num">${S.cfg.scoring.windows.primary_hours}h</th><th class="num">${S.cfg.scoring.windows.secondary_hours}h</th><th class="num">LinkedIn</th><th class="num">Portals</th><th class="num">Min</th></tr></thead><tbody>${hist.map(h => `<tr><td>${esc(fmtIST(h.started))}<div class="sub">${esc(h.trigger)}</div></td><td class="num">${h.qualified_primary}</td><td class="num">${h.qualified_secondary}</td><td class="num">${h.linkedin_ok}/${h.linkedin_queries}</td><td class="num">${h.ats_ok}</td><td class="num">${Math.round(h.duration_seconds / 60)}</td></tr>`).join('')}</tbody></table></div>` : '<p class="sub">No history yet.</p>'}</div>
    </div>
    <details class="fold" data-testid="fold-company-queries"><summary>LinkedIn company queries <span>${cq.length} run, ${gaps(cq)} with gaps${capN(cq) ? `, ${capN(cq)} reached the page limit` : ''}</span></summary>${qTable(cq)}</details>
    <details class="fold" data-testid="fold-skill-queries"><summary>LinkedIn skill queries <span>${sq.length} run, ${gaps(sq)} with gaps${capN(sq) ? `, ${capN(sq)} reached the page limit` : ''}</span></summary>${qTable(sq)}</details>
    <details class="fold" data-testid="fold-portals"><summary>Career portal feeds <span>${at.ok ?? 0} of ${at.configured ?? 0} answered</span></summary><div class="tablewrap"><table><thead><tr><th>Employer</th><th>System</th><th>State</th><th class="num">Relevant India roles</th><th>Detail</th></tr></thead><tbody>${Object.entries(st.ats || {}).map(([id, a]) => `<tr><td><b>${esc(emp(id)?.name || id)}</b></td><td>${esc(pname(a.type))}</td><td>${stateTag(a.state)}</td><td class="num">${a.returned ?? '—'}</td><td class="sub">${esc(a.error || '')}</td></tr>`).join('')}</tbody></table></div></details>
  </section>`;
}

/* ---------------------------------------------------------------- logic */
function viewLogic() {
  const sc = S.cfg.scoring, w = sc.weights, win = sc.windows, se = S.cfg.search;
  const pat = p => esc(p.replace(/\\b/g, '').replace(/\\/g, '').replace(/ \?/g, ' '));
  const roleRows = ['core', 'strong', 'adjacent', 'weak'].map(k => { const r = sc.role[k]; return `<tr><td><b>${esc(r.label)}</b></td><td class="num">${r.points}${r.boost_points ? ` → ${r.boost_points}` : ''}</td><td class="num">${r.boost_cap ? `${r.cap} → ${r.boost_cap}` : r.cap}</td><td class="sub">${r.patterns.slice(0, 14).map(pat).join(', ')}${r.patterns.length > 14 ? `, +${r.patterns.length - 14} more` : ''}</td></tr>`; }).join('');
  const skillRows = Object.entries(sc.skills).filter(([, g]) => g && g.terms).map(([k, g]) => `<tr><td><b>${esc(k[0].toUpperCase() + k.slice(1))}</b></td><td class="num">${g.each}</td><td class="num">${g.cap}</td><td class="sub">${Object.keys(g.terms).map(esc).join(', ')}</td></tr>`).join('');
  const senRows = sc.seniority.levels.map(l => `<tr><td><b>${esc(l.label)}</b></td><td class="num">${l.points}${l.tier1_points ? ` (${l.tier1_points} at tier-1 banks)` : ''}${l.top_tier_points ? ` (${l.top_tier_points} at GS, JPM, MS, MBB)` : ''}</td><td class="num">${l.cap}${l.tier1_cap ? ` (${l.tier1_cap})` : ''}</td><td class="sub">${l.junior ? 'Filtered out below the top-tier firms' : ''}</td></tr>`).join('');
  const tierPts = Object.entries(sc.employer.tier_points).map(([t, p]) => `<tr><td><b>${t}</b></td><td>${esc(S.cfg.tiers[t])}</td><td class="num">${p}</td></tr>`).join('');
  return `<section class="view"><div class="grid2">
  <div class="doc">
    <h2 class="h2">How the search runs</h2>
    <p>One scan runs every day at <b>${esc(se.schedule.label)}</b> on GitHub Actions, and on demand from the Refresh button. It follows the six phases of the master prompt and publishes this page when it finishes.</p>
    <ol>
      <li><b>LinkedIn company scans.</b> One query per employer, restricted to that employer with LinkedIn’s company filter, for any of ${se.linkedin.company_terms.map(t => `“${esc(t)}”`).join(', ')}. Location India, most recent first, up to ${se.linkedin.max_pages_company} pages. An employer LinkedIn cannot identify falls back to a keyword match and is flagged under Coverage.</li>
      <li><b>LinkedIn skill searches.</b> The 15 aggregated queries in three sets, up to ${se.linkedin.max_pages_skill} pages each.</li>
      <li><b>Naukri.com.</b> One probe per scan. Naukri requires an interactive check, so its searches open from the Search launcher instead.</li>
      <li><b>Career portals.</b> Public job feeds on Workday, Oracle, Greenhouse, Lever and SmartRecruiters for employers that expose one, searched for ${se.ats.search_terms.map(t => `“${esc(t)}”`).join(', ')}.</li>
      <li><b>Deduplication and enrichment.</b> Listings merge on employer, normalised title and city. LinkedIn is the source of truth for posting time. The most promising unread roles get their description, applicant count and apply link read.</li>
      <li><b>Scoring and digest.</b> Every role is scored, the top 10 are written to a digest and the dashboard is republished.</li>
    </ol>
    <h3>Time windows</h3>
    <ul>
      <li><b>Primary: last ${win.primary_hours} hours.</b> Both LinkedIn phases run with this window first.</li>
      <li><b>Secondary: last ${win.secondary_hours} hours.</b> Added only when fewer than ${win.secondary_trigger_below} roles clear the threshold in the primary window.</li>
      <li><b>Verified fresh</b> means inside ${win.primary_hours}h and either found on two or more platforms, or a single-platform timestamp under ${win.verified_single_platform_hours}h.</li>
      <li><b>Portal dates are not trusted alone.</b> A role seen only on an employer portal is marked “Portal date · verify”.</li>
      <li>LinkedIn shows “1 day ago” for anything from 24 to 48 hours. A listing returned by the ${win.primary_hours}h filter is placed between 24h and ${win.primary_hours}h.</li>
      <li>Freshness is recalculated in your browser each time the page opens, so scores drift down as a listing ages. Roles stay for ${win.retain_days} days after they were last seen.</li>
    </ul>
    <h3>What gets filtered out</h3>
    <ul>${sc.exclusions.map(x => `<li><b>${esc(x.label)}.</b>${x.kept_when ? ' ' + esc(x.kept_when) : ''}</li>`).join('')}</ul>
    <h3>Refresh</h3>
    <ul><li>The schedule and the Refresh button start the same GitHub Actions workflow. Nothing runs on a paid service.</li><li>GitHub may start scheduled runs late at busy times.</li><li>Tracking marks (Saved, Applied, Skip) stay in this browser only.</li></ul>
    <h3>Limits</h3>
    <ul><li>Sources are read logged-out. LinkedIn may rate limit; missing queries show as gaps under Coverage.</li><li>Scores are rule-based points, not a résumé match. Read the posting before applying.</li><li>${esc(sc.note)}</li></ul>
  </div>
  <div class="doc" style="max-width:none">
    <h2 class="h2">Scoring</h2>
    <div class="formula" data-testid="text-formula">FINAL_SCORE = min( cap,
    role fit        (0–${w.role})
  + skills match    (0–${w.skills})
  + employer tier   (0–${w.employer})
  + seniority       (0–${w.seniority})
  + location        (0–${w.location})
  + freshness       (0–${w.freshness}) )</div>
    <div class="tablewrap"><table><thead><tr><th>Band</th><th>Score</th><th>Meaning</th></tr></thead><tbody>${sc.bands.map(b => `<tr><td><span class="score ${bandCls(b.label)}" style="width:auto;height:auto;padding:4px 8px;display:inline-block">${esc(b.label)}</span></td><td>${esc(b.range)}</td><td>${esc(b.meaning)}</td></tr>`).join('')}<tr><td class="muted">Below</td><td>Under ${sc.threshold}</td><td>Filtered out</td></tr></tbody></table></div>
    <h3>Role fit, from the title</h3>
    <div class="tablewrap"><table><thead><tr><th>Class</th><th class="num">Points</th><th class="num">Cap</th><th>Matches</th></tr></thead><tbody>${roleRows}</tbody></table></div>
    <p>An adjacent title rises to ${sc.role.adjacent.boost_points} points when the description names ${sc.role.adjacent.boost_core_hits} or more core credit-risk terms. A bare grade title such as “Manager” or “Assistant Vice President” from a target employer’s credit-risk search scores ${sc.role.generic.points} when its description names “credit risk” and at least ${sc.role.generic.min_core_hits} core terms.</p>
    <h3>Skills match, from the description</h3>
    <div class="tablewrap"><table><thead><tr><th>Group</th><th class="num">Each</th><th class="num">Max</th><th>Terms</th></tr></thead><tbody>${skillRows}</tbody></table></div>
    <p>When a description has not been read, skills are estimated at ${Math.round(sc.skills.title_only_scale * 100)}% of the role-fit share and the role is tagged “Title only”.</p>
    <h3>Seniority</h3>
    <div class="tablewrap"><table><thead><tr><th>Grade</th><th class="num">Points</th><th class="num">Cap</th><th></th></tr></thead><tbody>${senRows}</tbody></table></div>
    <p>The cap keeps grades in the bands the master prompt assigns them: only VP, AVP and Director titles can reach Tier 1.</p>
    <h3>Employer</h3>
    <div class="tablewrap"><table><thead><tr><th>Tier</th><th>Group</th><th class="num">Points</th></tr></thead><tbody>${tierPts}<tr><td class="muted">—</td><td>Other financial-sector employer</td><td class="num">${sc.employer.non_target_financial}</td></tr><tr><td class="muted">—</td><td>Any other employer</td><td class="num">${sc.employer.non_target_other}</td></tr></tbody></table></div>
    <h3>Location and freshness</h3>
    <div class="tablewrap"><table><thead><tr><th>Rule</th><th class="num">Points</th></tr></thead><tbody>
      <tr><td>${Object.keys(sc.location.primary.cities).map(esc).join(', ')}</td><td class="num">${sc.location.primary.points}</td></tr>
      <tr><td>${Object.keys(sc.location.secondary.cities).map(esc).join(', ')}</td><td class="num">${sc.location.secondary.points}</td></tr>
      <tr><td>Remote or hybrid in India</td><td class="num">${sc.location.remote.points}</td></tr><tr><td>Elsewhere in India</td><td class="num">${sc.location.other_india.points}</td></tr>
      ${sc.freshness.age_points.map(a => `<tr><td>Posted within ${a.max_hours >= 168 ? '7 days' : a.max_hours + 'h'}</td><td class="num">${a.points}</td></tr>`).join('')}
      ${sc.freshness.applicant_points.map(a => `<tr><td>Up to ${a.max} applicants</td><td class="num">+${a.points}</td></tr>`).join('')}
    </tbody></table></div>
  </div></div></section>`;
}

/* ---------------------------------------------------------------- refresh */
function issueUrl() { return `${GH}/issues/new?` + new URLSearchParams({title: '[SCAN] Refresh requested from dashboard', body: 'Opened from the dashboard Refresh button. Submitting this issue starts a scan; the workflow closes it when the scan ends.'}).toString(); }
function openRefresh() {
  const running = S.run && S.run.status !== 'completed', token = store.get('token', '');
  const m = $('#modal');
  m.innerHTML = `<div class="in" data-testid="modal-refresh">
    <div class="dhead"><div><h2 class="h2">Refresh the scan</h2><p class="sub">A scan takes 30 to 60 minutes on GitHub Actions. This page updates itself when it finishes.</p></div><button class="btn ghost icon x" data-act="close-modal" data-testid="button-close-modal" aria-label="Close">${ico('x')}</button></div>
    ${running ? `<div class="note">${ico('info')}<span>A scan is already running. ${ext(S.run.html_url, 'Watch it on GitHub')}</span></div>` : ''}
    <div class="steps">
      ${token ? `<div class="step"><h3>Start now</h3><p>Uses the access token saved in this browser.</p><div class="row"><button class="btn primary" data-act="dispatch" data-testid="button-dispatch"${running ? ' disabled' : ''}>${ico('refresh')} Start scan</button><button class="btn" data-act="forget-token" data-testid="button-forget-token">Forget token</button></div></div>` : ''}
      <div class="step"><h3>${token ? 'Or start on GitHub' : 'Start on GitHub'}</h3><p>Opens a pre-filled scan request. Press “Create” on GitHub and the scan starts. Only the repository owner can trigger it.</p><div class="row">${ext(issueUrl(), 'Open scan request ' + ico('out'), 'btn' + (token ? '' : ' primary'), 'link-issue')}${ext(`${GH}/actions/workflows/${WORKFLOW}`, 'Run workflow page ' + ico('out'), 'btn', 'link-workflow')}</div></div>
      ${token ? '' : `<div class="step"><h3>One-click refresh</h3><p>Paste a fine-grained GitHub token limited to this repository with Actions read and write. It is stored only in this browser${store.persistent ? '' : ' tab'}.</p><div class="row"><label class="sr" for="tok">GitHub token</label><input type="password" id="tok" data-testid="input-token" placeholder="github_pat_…" autocomplete="off"><button class="btn" data-act="save-token" data-testid="button-save-token">Save and start</button></div><p>${ext('https://github.com/settings/personal-access-tokens/new', 'Create a token')}</p></div>`}
      <div class="step"><h3>Reload results</h3><p>Fetch the latest published data without starting a scan.</p><div class="row"><button class="btn" data-act="reload" data-testid="button-reload">Reload data</button></div></div>
    </div></div>`;
  if (!m.open) m.showModal();
}
async function dispatch(token) {
  try {
    const r = await fetch(`${API}/actions/workflows/${WORKFLOW}/dispatches`, {method: 'POST', headers: {Accept: 'application/vnd.github+json', Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'}, body: JSON.stringify({ref: 'main'})});
    if (r.status === 204) { $('#modal').close(); toast('Scan started. This page updates when it finishes.'); S.run = {status: 'queued', created_at: new Date().toISOString(), html_url: `${GH}/actions/workflows/${WORKFLOW}`}; renderScanState(); clearTimeout(S._poll); S._poll = setTimeout(checkRun, 20000); return true; }
    toast(r.status === 401 || r.status === 403 ? 'GitHub rejected the token. Check its repository and Actions permission.' : `GitHub answered ${r.status}. Use the scan request link instead.`);
  } catch (e) { toast('Could not reach GitHub. Use the scan request link instead.'); }
  return false;
}
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(S._toast); S._toast = setTimeout(() => t.classList.remove('on'), 4500); }
function csv() {
  const rows = filtered(), q = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const head = ['Score', 'Tier', 'Title', 'Company', 'Category', 'City', 'Posted (IST)', 'Age hours', 'Freshness', 'Applicants', 'Platforms', 'Apply URL', 'Filtered out'];
  const lines = [head.join(',')].concat(rows.map(({j, L}) => [L.total, L.band || '', j.title, j.company, j.tier || '', j.city, j.posted_at ? fmtIST(j.posted_at) : '', L.age == null ? '' : L.age.toFixed(1), L.fs.label, j.applicants_text || '', j.platforms.join(' '), applyUrl(j), L.excluded ? exLabel(L.excluded) : ''].map(q).join(',')));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['\ufeff' + lines.join('\r\n')], {type: 'text/csv'}));
  a.download = `credit-risk-roles-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/* ---------------------------------------------------------------- render + events */
function render(keepFocus) {
  const main = $('#main');
  renderScanState(); renderTabs();
  if (!S.loaded) { main.innerHTML = `<section class="view"><div class="kpis">${'<div class="kpi"><div class="skeleton" style="height:28px;width:60%"></div><div class="skeleton" style="height:14px;width:80%;margin-top:10px"></div></div>'.repeat(6)}</div><div class="skeleton" style="height:320px"></div></section>`; return; }
  if (S.loadError || !S.cfg) { main.innerHTML = `<section class="view"><div class="panel empty" data-testid="error-load"><h3>Could not load the published data</h3><p>${esc(S.loadError || 'Unknown error')}</p><button class="btn primary" data-act="reload">Try again</button></div></section>`; return; }
  const focusId = keepFocus && document.activeElement?.id, pos = focusId === 'q' ? document.activeElement.selectionStart : null;
  main.innerHTML = ({shortlist: viewShortlist, employers: viewEmployers, launcher: viewLauncher, coverage: viewCoverage, logic: viewLogic}[S.tab])();
  if (focusId === 'q') { const q = $('#q'); q.focus(); q.setSelectionRange(pos, pos); }
}
function setTheme(t) { document.documentElement.dataset.theme = t; store.set('theme', t); $('#btn-theme').innerHTML = ico(t === 'dark' ? 'sun' : 'moon'); }

document.addEventListener('click', async e => {
  const t = e.target.closest('[data-tab],[data-act],[data-open],[data-window],[data-band],[data-sort],[data-ecat],[data-check],[data-goto],#btn-refresh,#btn-theme');
  if (!t) return;
  if (e.target.closest('a[href]') && !t.dataset.goto) return;
  if (e.target.closest('select')) return;
  const d = t.dataset;
  if (t.id === 'btn-refresh') return openRefresh();
  if (t.id === 'btn-theme') return setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  if (d.tab) { S.tab = d.tab; render(); window.scrollTo(0, 0); return; }
  if (d.goto) { e.preventDefault(); S.tab = d.goto; render(); window.scrollTo(0, 0); return; }
  if (d.open) return openDrawer(d.open);
  if (d.window != null) { S.f.window = +d.window; S.limit = 50; return render(); }
  if (d.band) { S.f.bands.has(d.band) ? S.f.bands.delete(d.band) : S.f.bands.add(d.band); S.limit = 50; return render(); }
  if (d.sort) { S.sort = S.sort.key === d.sort ? {key: d.sort, dir: -S.sort.dir} : {key: d.sort, dir: d.sort === 'company' ? 1 : -1}; return render(); }
  if (d.ecat != null) { S.empF.category = d.ecat; return render(); }
  if (d.check) { S.checks[d.check] = new Date().toISOString(); store.set('checks', S.checks); return render(); }
  switch (d.act) {
    case 'refresh': return openRefresh();
    case 'more': S.limit += 50; return render();
    case 'clear': S.f = {window: 0, bands: new Set(), category: '', city: '', platform: '', target: false, verified: false, hideDone: false, excluded: false, q: ''}; return render();
    case 'csv': return csv();
    case 'close-drawer': return $('#drawer').close();
    case 'close-modal': return $('#modal').close();
    case 'reload': { $('#modal').open && $('#modal').close(); S.loaded = !!S.cfg; const ch = await load(true); render(); toast(S.loadError ? 'Could not load data.' : ch ? 'Results updated.' : 'Already showing the latest results.'); checkRun(); return; }
    case 'dispatch': return dispatch(store.get('token', ''));
    case 'save-token': { const v = $('#tok').value.trim(); if (!v) return toast('Paste a token first.'); if (await dispatch(v)) store.set('token', v); return; }
    case 'forget-token': store.del('token'); toast('Token removed from this browser.'); return openRefresh();
  }
});
document.addEventListener('change', e => {
  const t = e.target, d = t.dataset;
  if (d.f) { S.f[d.f] = t.value; S.limit = 50; render(); }
  else if (d.t) { S.f[d.t] = t.checked; S.limit = 50; render(); }
  else if (d.et) { S.empF[d.et] = t.checked; render(); }
  else if (d.mark) { if (t.value) S.marks[d.mark] = t.value; else delete S.marks[d.mark]; store.set('marks', S.marks); const inDrawer = !!t.closest('#drawer'); render(); if (inDrawer) openDrawer(d.mark); }
});
document.addEventListener('input', e => { if (e.target.id === 'q') { S.f.q = e.target.value; S.limit = 50; clearTimeout(S._q); S._q = setTimeout(() => render(true), 120); } });
document.addEventListener('keydown', e => { const r = e.target.closest?.('tr[data-open]'); if (r && e.key === 'Enter') openDrawer(r.dataset.open); });
for (const id of ['drawer', 'modal']) $('#' + id).addEventListener('click', e => { if (e.target === e.currentTarget) e.currentTarget.close(); });
$('#skip-link').addEventListener('click', e => { e.preventDefault(); $('#main').focus(); });

document.querySelectorAll('[data-ico]').forEach(n => { n.innerHTML = ico(n.dataset.ico); });
setTheme(store.get('theme', null) || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
render();
load().then(() => { render(); checkRun(); });
setInterval(() => { if (document.visibilityState === 'visible' && S.loaded && !S.loadError) { renderScanState(); } }, 60000);
setInterval(async () => { if (document.visibilityState === 'visible') { if (await load(true)) render(); checkRun(); } }, 15 * 60000);
})();
