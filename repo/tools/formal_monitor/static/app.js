const $ = id => document.getElementById(id);
const fmt = s => s == null ? '—' : s < 60 ? `${Math.round(s)} s` :
  s < 3600 ? `${(s / 60).toFixed(1)} min` : `${(s / 3600).toFixed(1)} h`;
const pct = v => v == null ? '—' : `${Number(v).toFixed(1)}%`;
const bytes = v => v == null ? '—' : `${(v / 1073741824).toFixed(2)} GiB`;
const value = v => v == null || v === '' ? '—' : String(v);

function renderDiagnostics(s) {
  const error = s.error_diagnostic;
  const panel = $('error-diagnostic');
  panel.hidden = !error;
  if (error) {
    const historical = error.historical === true || error.status === 'RESOLVED/HISTORICAL';
    $('current-error-heading').hidden = historical;
    $('error-history-heading').hidden = !historical;
    $('error-status').textContent = value(error.status || 'ACTIVE');
    $('error-type').textContent = value(error.error_type);
    $('error-message').textContent = value(error.message);
    $('error-timestamp').textContent = value(error.timestamp);
    $('error-run').textContent = value(error.simulation_run);
    $('error-component').textContent = value(error.component);
    $('error-exit-code').textContent = value(error.exit_code);
    $('error-first-causal').textContent = value(error.first_causal_stderr);
    $('error-log-path').textContent = value(error.log_path);
    $('error-stderr-path').textContent = value(error.component_stderr_path);
    $('error-stdout-path').textContent = value(error.component_stdout_path);
    $('error-traceback').textContent = value(error.traceback);
    $('error-component-stderr').textContent = value(error.component_stderr);
    $('error-component-stdout').textContent = value(error.component_stdout);
    $('error-component-command').textContent = value(error.component_command);
  }
  const container = $('operational-events');
  container.replaceChildren();
  [...(s.operational_events || [])].reverse().forEach(event => {
    const row = document.createElement('div');
    row.className = `log-event ${String(event.level || 'info').toLowerCase()}`;
    const timestamp = document.createElement('time');
    timestamp.textContent = value(event.timestamp);
    const type = document.createElement('span');
    type.className = 'event-type';
    type.textContent = value(event.event_type);
    const message = document.createElement('span');
    const context = [event.run_event_id, event.component,
      event.simulation_run == null ? null : `run ${event.simulation_run}`]
      .filter(Boolean).join(' · ');
    message.textContent = context ? `${event.message} — ${context}` : event.message;
    row.append(timestamp, type, message);
    container.append(row);
  });
}

async function action(name, payload = {}) {
  await fetch(`/api/action/${name}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  await refresh();
}

async function refresh() {
  const s = await fetch('/api/state', {cache: 'no-store'}).then(r => r.json());
  $('global-status').textContent = s.global_status;
  $('global-status').className = `status ${s.global_status.toLowerCase()}`;
  $('gate-banner').hidden = !s.formal_execution_blocked;
  $('gate-reasons').textContent = (s.gate_reasons || []).join(' · ');
  $('cohort').textContent = s.cohort;
  $('batch-count').textContent = `${s.completed_batches} / ${s.total_batches} COMPLETE`;
  $('total-bar').style.width = `${s.progress_total_percent}%`;
  $('simulation-run').textContent = s.current_simulation_run ?? '—';
  const completedWindows = s.completed_windows ?? s.window_completed;
  const currentWindow = s.current_window ?? s.window_completed;
  const maxWindows = s.max_windows ?? s.window_total_max;
  $('completed-windows').textContent = completedWindows;
  $('window-count').textContent = `${currentWindow} / ${maxWindows} máximo`;
  $('batch-bar').style.width = `${s.progress_batch_percent}%`;
  $('detection-state').textContent = s.detection_state;
  $('first-window').textContent = s.first_indication_window ?? '—';
  $('verification').textContent =
    `${s.verification_advance} / ${s.verification_advances_required} advances`;
  $('confirmation-window').textContent = s.confirmation_window ?? '—';
  $('early-stop').textContent = s.early_stop == null ? '—' :
    s.early_stop ? 'SIM' : 'NÃO';
  $('last-decision').textContent = s.last_llm_decision ?? '—';
  $('llm-status').textContent = s.llm_status;
  $('dpca-status').textContent = s.dpca_status;
  $('lot-status').textContent = s.lot_status;
  $('batch-time').textContent = fmt(s.active_batch_seconds);
  $('total-time').textContent = fmt(s.accumulated_active_seconds);
  $('batch-eta').textContent = fmt(s.eta_batch_seconds);
  $('total-eta').textContent = fmt(s.eta_total_seconds);
  const r = s.resources || {};
  $('host-cpu').textContent = pct(r.host_cpu_percent);
  $('experiment-cpu').textContent = pct(r.experiment_cpu_percent);
  $('host-ram').textContent =
    `${bytes(r.host_ram_used_bytes)} / ${bytes(r.host_ram_total_bytes)}`;
  $('container-ram').textContent =
    `${bytes(r.container_ram_used_bytes)} / ${bytes(r.container_ram_limit_bytes)}`;
  $('gpu-name').textContent = r.gpu_name ?? '—';
  $('gpu-util').textContent = pct(r.gpu_util_percent);
  $('vram').textContent = r.vram_used_mib == null ? '—' :
    `${r.vram_used_mib} / ${r.vram_total_mib} MiB`;
  renderDiagnostics(s);
  $('start').disabled = !(s.mock_start_enabled || s.real_start_enabled);
  $('revalidate').disabled = !s.operational_revalidation_enabled;
}

$('start').onclick = () => action('start', {
  runs_this_session: Number($('runs-this-session').value || 5),
});
$('revalidate').onclick = () => action('revalidate');
$('stop-after').onclick = () => action('stop-after-current');
$('stop-now').onclick = () => action('stop-now');
refresh();
setInterval(refresh, 2000);
