'use strict';
const $ = id => document.getElementById(id);
let offset = 0, generation = 0, stopped = false, busy = false, connected = false, status = null, timer;
const pageSize = 100;
const number = value => new Intl.NumberFormat().format(value);
const clock = timestamp => new Date(timestamp * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});
const dayString = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
function duration(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m`;
}
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function bounds() {
  if (!/^\d{4}-\d{2}-\d{2}$/.test($('day').value)) throw new Error('Choose a valid day.');
  const start = new Date($('day').value + 'T00:00:00');
  const end = new Date(start);
  end.setDate(end.getDate() + 1); // Correct for local 23/25-hour daylight-saving days.
  return {start: start.getTime() / 1000, end: end.getTime() / 1000};
}
function options() {
  return new URLSearchParams({...bounds(), q: $('search').value, kind: $('kind').value, offset, limit: pageSize});
}
async function api(path, body) {
  const response = await fetch(path, {method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
    headers: body ? {'Content-Type': 'application/json', 'X-Tracker-Action': '1'} : {},
    body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(12000)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'The local recorder did not respond.');
  return data;
}
function showError(error) {
  $('network-message').textContent = error.message || 'The local recorder is unavailable.';
  $('network-error').hidden = false;
}
function renderStatus(next) {
  status = next;
  const labels = {starting: 'Starting', recording: 'Recording', paused: 'Paused', error: 'Not recording', stopped: 'Stopped'};
  $('recording-state').textContent = labels[next.state] || 'Not recording';
  $('status-pill').dataset.state = next.state;
  $('record-toggle').textContent = next.state === 'recording' ? 'Pause recording' : (next.state === 'paused' ? 'Resume recording' : 'Start recording');
  $('record-toggle').disabled = busy || stopped;
  $('quit').disabled = busy || stopped;
  $('database-path').textContent = next.database;
  $('idle-threshold').textContent = duration(next.idle_timeout);
  $('recording-detail').textContent = next.message;
  $('capture-warning').textContent = next.message;
  $('capture-warning').hidden = next.state !== 'error';
}
function chart(data) {
  const svg = $('activity-chart');
  const nodes = [];
  const create = (name, attributes) => {
    const item = document.createElementNS('http://www.w3.org/2000/svg', name);
    for (const [key, value] of Object.entries(attributes)) item.setAttribute(key, String(value));
    return item;
  };
  for (const y of [12, 56, 100, 144]) nodes.push(create('line', {x1: 0, x2: 960, y1: y, y2: y, class: 'chart-grid'}));
  const peak = Math.max(0, ...data.bins.map(bin => bin.active_seconds + bin.afk_seconds));
  const max = Math.max(1, peak);
  data.bins.forEach((bin, index) => {
    const active = bin.active_seconds / max * 124, away = bin.afk_seconds / max * 124;
    const group = create('g', {});
    const title = create('title', {});
    title.textContent = `${clock(bin.start)}: ${duration(bin.active_seconds)} active, ${duration(bin.afk_seconds)} away`;
    group.append(title);
    if (active) group.append(create('rect', {x: index * 40 + 4, y: 144 - active, width: 26, height: active, rx: 2, class: 'chart-active'}));
    if (away) group.append(create('rect', {x: index * 40 + 4, y: 144 - active - away, width: 26, height: away, rx: 2, class: 'chart-afk'}));
    if (!active && !away) group.append(create('rect', {x: index * 40 + 4, y: 142, width: 26, height: 2, rx: 1, class: 'chart-empty'}));
    nodes.push(group);
  });
  svg.replaceChildren(...nodes);
  $('chart-midpoint').textContent = new Date((data.start + data.end) / 2 * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  $('chart-caption').textContent = `${duration(data.active_seconds)} active and ${duration(data.afk_seconds)} away, in 24 equal intervals. Tallest interval: ${duration(peak)}. Blank space is unrecorded time, not assumed work or rest.`;
}
function renderApps(data) {
  $('app-count').textContent = `${number(data.apps.length)} ${data.apps.length === 1 ? 'app' : 'apps'}`;
  $('apps-empty').hidden = data.apps.length > 0;
  $('apps-list').replaceChildren(...data.apps.map(app => {
    const row = element('div', 'app-row');
    const icon = element('span', 'app-icon', app.app.slice(0, 1).toUpperCase());
    icon.setAttribute('aria-hidden', 'true');
    const meter = element('meter', 'app-meter');
    meter.min = 0; meter.max = Math.max(data.active_seconds, 1); meter.value = app.seconds;
    meter.setAttribute('aria-label', `${app.app}: ${duration(app.seconds)}`);
    row.append(icon, element('span', 'app-name', app.app), meter, element('span', 'app-duration', duration(app.seconds)),
      element('span', 'app-percent', `${Math.round(app.seconds / Math.max(data.active_seconds, 1) * 100)}%`));
    return row;
  }));
}
function renderTimeline(data) {
  $('timeline-body').replaceChildren(...data.events.map(event => {
    const row = document.createElement('tr');
    const name = element('td');
    name.append(element('span', event.kind === 'afk' ? 'event-app event-afk' : 'event-app', event.kind === 'afk' ? 'Away from keyboard' : event.app));
    name.append(element('span', 'event-title', event.kind === 'afk' ? 'No input past the idle threshold' : event.title));
    row.append(element('td', '', clock(event.start)), name, element('td', '', duration(event.seconds)), element('td', '', event.kind === 'afk' ? '·' : number(event.keys)));
    return row;
  }));
  $('matching-count').textContent = `${number(data.matching_count)} matching events`;
  $('timeline-empty').hidden = data.events.length > 0;
  $('page-range').textContent = data.events.length ? `${number(offset + 1)} to ${number(offset + data.events.length)} of ${number(data.matching_count)}` : '0 events';
  $('previous-page').disabled = offset === 0;
  $('next-page').disabled = !data.has_more;
}
function renderReport(data) {
  $('active-total').textContent = duration(data.active_seconds);
  $('afk-total').textContent = duration(data.afk_seconds);
  $('key-total').textContent = number(data.key_count);
  $('event-total').textContent = number(data.event_count);
  $('overview-empty').hidden = data.event_count > 0;
  chart(data); renderApps(data); renderTimeline(data);
  $('updated-at').textContent = `Updated ${new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'})}`;
  document.body.classList.remove('loading');
  $('export').disabled = stopped;
}
async function refresh() {
  if (stopped) return;
  const request = ++generation;
  try {
    const [nextStatus, report] = await Promise.all([api('/api/status'), api('/api/report?' + options())]);
    if (request !== generation || stopped) return;
    connected = true;
    $('network-error').hidden = true;
    renderStatus(nextStatus); renderReport(report);
  } catch (error) {
    if (request !== generation || stopped) return;
    connected = false;
    $('recording-state').textContent = 'Disconnected';
    $('status-pill').dataset.state = 'offline';
    $('record-toggle').disabled = true; $('quit').disabled = true; $('export').disabled = true;
    $('updated-at').textContent = 'Disconnected. Values shown may be out of date.';
    showError(error);
  }
}
function view() {
  const name = ['overview', 'timeline', 'privacy'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'overview';
  for (const link of document.querySelectorAll('nav a')) {
    if (link.dataset.view === name) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    $('view-' + link.dataset.view).hidden = link.dataset.view !== name;
  }
  $('page-title').textContent = {overview: 'Day overview', timeline: 'Your activity timeline', privacy: 'Privacy & data'}[name];
  $('page-description').textContent = {overview: 'Where your computer time went. No productivity score attached.', timeline: 'A searchable record of focused windows and time away.', privacy: 'Understand what is captured, where it lives, and how to stop.'}[name];
}
function changeDay(delta) {
  const date = new Date($('day').value + 'T12:00:00');
  date.setDate(date.getDate() + delta);
  $('day').value = dayString(date); updateDay();
}
function updateDay() {
  offset = 0;
  $('day').max = dayString(new Date());
  $('next-day').disabled = $('day').value >= $('day').max;
  $('day-description').textContent = new Date($('day').value + 'T12:00:00').toLocaleDateString([], {weekday: 'long', month: 'long', day: 'numeric', year: 'numeric'}).toUpperCase();
  refresh();
}
function onClick(id, action) { $(id).addEventListener('click', () => Promise.resolve().then(action).catch(showError)); }
onClick('record-toggle', async () => {
  if (!connected || busy || stopped) return;
  busy = true; renderStatus(status);
  try { renderStatus(await api('/api/control', {action: status.state === 'recording' ? 'pause' : 'resume'})); }
  finally { busy = false; await refresh(); }
});
onClick('quit', () => $('quit-dialog').showModal());
onClick('cancel-quit', () => $('quit-dialog').close());
onClick('confirm-quit', async () => {
  $('confirm-quit').disabled = true;
  try {
    const next = await api('/api/control', {action: 'quit'});
    stopped = true; generation++; clearInterval(timer);
    $('quit-dialog').close(); renderStatus(next);
    $('export').disabled = true;
    $('updated-at').textContent = 'Tracker stopped. Reopen the app to continue.';
  } finally { $('confirm-quit').disabled = false; }
});
onClick('export', async () => {
  $('export').disabled = true;
  try {
    const format = $('export-format').value;
    const response = await fetch('/api/export.' + format + '?' + options(), {credentials: 'same-origin', signal: AbortSignal.timeout(30000)});
    if (!response.ok) throw new Error((await response.json()).error || 'Export failed.');
    const url = URL.createObjectURL(await response.blob());
    const anchor = element('a'); anchor.href = url; anchor.download = `activity-${$('day').value}.${format}`;
    document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } finally { $('export').disabled = stopped || !connected; }
});
onClick('retry', refresh);
onClick('previous-day', () => changeDay(-1)); onClick('next-day', () => changeDay(1));
onClick('today', () => { $('day').value = dayString(new Date()); updateDay(); });
onClick('previous-page', () => { offset = Math.max(0, offset - pageSize); return refresh(); });
onClick('next-page', () => { offset += pageSize; return refresh(); });
$('day').addEventListener('change', updateDay);
$('kind').addEventListener('change', () => { offset = 0; refresh(); });
let searchTimer;
$('search').addEventListener('input', () => { generation++; clearTimeout(searchTimer); searchTimer = setTimeout(() => { offset = 0; refresh(); }, 200); });
window.addEventListener('hashchange', view);
document.addEventListener('keydown', event => { if (event.key === '/' && !event.ctrlKey && !event.metaKey && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {event.preventDefault(); location.hash = 'timeline'; view(); $('search').focus();} });
async function boot() {
  $('day').value = dayString(new Date()); $('day').max = $('day').value;
  $('timezone').textContent = Intl.DateTimeFormat().resolvedOptions().timeZone + ' · local dates';
  const token = location.hash.slice(1);
  if (/^[A-Za-z0-9_-]{43}$/.test(token)) {
    history.replaceState(null, '', location.pathname);
    await api('/api/session', {token});
  }
  view(); updateDay();
  timer = setInterval(() => { if (!document.hidden && !busy) refresh(); }, 3000);
}
boot().catch(showError);
