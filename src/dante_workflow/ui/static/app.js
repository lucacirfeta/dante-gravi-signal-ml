const initialWorkerState = document.getElementById('worker-state')?.textContent.trim();
const initialSmokeStatus = document.getElementById('smoke-status')?.dataset.status;

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return 'Time estimate unavailable';
  if (seconds < 60) return `Approximate time remaining: ${Math.max(1, Math.round(seconds))} seconds`;
  const minutes = Math.ceil(seconds / 60);
  return `Approximate time remaining: ${minutes} minute${minutes === 1 ? '' : 's'}`;
}

function verificationLabel(value) {
  return value === 'VERIFIED_TECHNICAL_SMOKE' ? 'Verified (PASS)' : 'Pending';
}

function updateLogFiles(logs, device) {
  const list = document.getElementById('smoke-log-list');
  if (!list || !logs) return;
  list.replaceChildren();
  if (!logs.files.length) {
    const empty = document.createElement('li');
    empty.className = 'empty';
    empty.textContent = 'No detailed log is available yet.';
    list.appendChild(empty);
    return;
  }
  for (const log of logs.files) {
    const item = document.createElement('li');
    const link = document.createElement('a');
    const encodedPath = log.path.split('/').map(encodeURIComponent).join('/');
    link.href = `/logs/${encodedPath}?device=${encodeURIComponent(device)}`;
    link.textContent = log.name;
    const size = document.createElement('span');
    size.textContent = `${log.size_bytes} bytes`;
    item.append(link, size);
    list.appendChild(item);
  }
}

async function refreshStatus() {
  try {
    const device = new URLSearchParams(window.location.search).get('device');
    const query = device ? `?device=${encodeURIComponent(device)}` : '';
    const response = await fetch(`/api/status${query}`, {cache: 'no-store'});
    if (!response.ok) throw new Error('status unavailable');
    const status = await response.json();
    const worker = document.getElementById('worker-state');
    const next = document.getElementById('next-stage');
    if (worker) {
      worker.textContent = status.worker.state;
      worker.className = `state state-${status.worker.state.toLowerCase()}`;
    }
    if (next) next.textContent = status.next_incomplete_stage || 'COMPLETE';
    if (Array.isArray(status.stages)) {
      for (const stage of status.stages) {
        const badge = document.querySelector(`[data-stage="${stage.name}"]`);
        if (badge) {
          badge.textContent = stage.status;
          badge.className = `badge badge-${stage.status.toLowerCase()}`;
        }
      }
    }
    const smokeStatus = document.getElementById('smoke-status');
    if (smokeStatus) {
      smokeStatus.textContent = verificationLabel(status.status);
      smokeStatus.dataset.status = status.status;
      smokeStatus.className = `state state-${status.status === 'VERIFIED_TECHNICAL_SMOKE' ? 'verified' : 'running'}`;
    }
    const phase = document.getElementById('current-phase');
    const detail = document.getElementById('phase-detail');
    const progress = document.getElementById('smoke-progress');
    const percent = document.getElementById('progress-percent');
    const step = document.getElementById('progress-step');
    const eta = document.getElementById('progress-eta');
    if (status.progress) {
      if (phase) phase.textContent = status.progress.label;
      if (detail) detail.textContent = status.progress.detail;
      if (progress) progress.value = status.progress.percent;
      if (percent) percent.textContent = `${status.progress.percent}%`;
      if (step) step.textContent = `Step ${status.progress.completed_steps} of ${status.progress.total_steps}`;
      if (eta) {
        eta.textContent = status.progress.status === 'COMPLETE'
          ? 'Complete'
          : status.progress.eta_seconds === null
          ? 'Time estimate becomes available after the first completed phase'
          : formatDuration(status.progress.eta_seconds);
      }
    }
    const activeLog = document.getElementById('active-log-name');
    const logTail = document.getElementById('log-tail');
    if (status.logs) {
      if (activeLog) activeLog.textContent = status.logs.active_name || 'No log yet';
      if (logTail) logTail.textContent = status.logs.active_tail || 'Logs will appear here after the worker starts.';
      updateLogFiles(status.logs, status.device);
    }
    const connection = document.getElementById('connection-status');
    if (connection) connection.firstChild.textContent = 'Connected. ';
    if (
      (initialWorkerState === 'ACTIVE' && status.worker.state !== 'ACTIVE') ||
      (initialSmokeStatus && initialSmokeStatus !== status.status && status.status === 'VERIFIED_TECHNICAL_SMOKE')
    ) {
      window.location.reload();
    }
  } catch (_) {
    const connection = document.getElementById('connection-status');
    if (connection) connection.firstChild.textContent =
      'Connection lost: displayed state may be stale; worker status is unknown. ';
  }
}
if (document.getElementById('worker-state') || document.getElementById('next-stage')) {
  window.setInterval(refreshStatus, 5000);
}
