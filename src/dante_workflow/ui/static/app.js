async function refreshStatus() {
  try {
    const response = await fetch('/api/status', {cache: 'no-store'});
    if (!response.ok) throw new Error('status unavailable');
    const status = await response.json();
    const worker = document.getElementById('worker-state');
    const next = document.getElementById('next-stage');
    if (worker) {
      worker.textContent = status.worker.state;
      worker.className = `state state-${status.worker.state.toLowerCase()}`;
    }
    if (next) next.textContent = status.next_incomplete_stage || 'COMPLETE';
    for (const stage of status.stages) {
      const badge = document.querySelector(`[data-stage="${stage.name}"]`);
      if (badge) {
        badge.textContent = stage.status;
        badge.className = `badge badge-${stage.status.toLowerCase()}`;
      }
    }
    const connection = document.getElementById('connection-status');
    if (connection) connection.firstChild.textContent = 'Connected. ';
  } catch (_) {
    const connection = document.getElementById('connection-status');
    if (connection) connection.firstChild.textContent =
      'Connection lost: displayed state may be stale; worker status is unknown. ';
  }
}
window.setInterval(refreshStatus, 5000);
