'use strict';
(() => {
  const el = id => document.getElementById(id);
  const terminal = new Set(['succeeded', 'failed', 'no_solution', 'cancelled', 'interrupted']);
  const labels = { running: '계산 중', verifying: '결과 검증·반영 중', succeeded: '완료 · 결과 반영됨',
    failed: '실패', no_solution: '가능해 없음 · 이전 결과 유지', cancelled: '중지됨', interrupted: '서버 종료로 중단됨' };
  let available = false, current = null, pending = false, revision = null;
  function controls() {
    const busy = Boolean(pending || (current && !terminal.has(current.status)));
    for (const id of ['runBoth', 'runMilp', 'runMeta', 'milpLimit', 'metaLimit', 'runSeed']) el(id).disabled = !available || busy;
    el('cancelRun').disabled = Boolean(!available || !busy || pending || current?.cancel_requested);
  }
  function render(job) {
    current = job;
    el('runConnection').textContent = available ? '로컬 실행 서버 연결됨' : '실행 서버 연결 필요';
    if (!job) { el('runStatus').textContent = '새 계산을 시작하려면 「둘 다 동시 실행」 또는 개별 실행 버튼을 누르세요.'; controls(); return; }
    const lines = [`실행 ${job.id} · ${job.cancel_requested && !terminal.has(job.status) ? '중지 처리 중' : labels[job.status] || job.status}`];
    for (const [name, task] of Object.entries(job.tasks)) lines.push(
      `${name === 'milp' ? 'MILP' : '메타휴리스틱 (Greedy + SA + Tabu)'}: ${labels[task.status] || task.status} · 경과 ${task.elapsed_seconds || 0}초${task.error ? '\n' + task.error : ''}`);
    if (!Object.keys(job.tasks).length && !terminal.has(job.status)) lines.push('공통 입력 스냅샷을 준비하고 있습니다.');
    if (job.error) lines.push(job.error);
    lines.push(`실행 기록: ${job.directory}`);
    el('runStatus').textContent = lines.join('\n');
    el('runLogs').textContent = Object.entries(job.tasks).map(([name, task]) => `=== ${name.toUpperCase()} ===\n${task.log || '로그 대기 중'}`).join('\n\n');
    controls();
  }
  async function request(url, options) {
    const response = await fetch(url, { cache: 'no-store', ...options });
    if (!response.ok) {
      let message = `실행 API 오류 (${response.status})`;
      try { message = (await response.json()).error || message; } catch {}
      throw Error(message);
    }
    return response.json();
  }
  async function poll() {
    try {
      const result = await request('/api/runs');
      available = result.available === true;
      if (!available) throw Error('실행 API가 없습니다.');
      const next = result.job ? result.job.id + ':' + result.job.revision : 'none';
      if (revision !== null && revision !== next && result.job?.revision > 0) {
        await refreshResults();
      }
      revision = next;
      render(result.job);
    } catch (error) {
      available = false; controls();
      el('runConnection').textContent = '실행 서버에 연결할 수 없습니다.';
      el('runStatus').textContent = error.message + '\n터미널에서 기존 서버를 Ctrl+C로 종료한 뒤 python3 dashboard/serve.py로 다시 시작하세요.';
    } finally { setTimeout(poll, 2000); }
  }
  async function start(target) {
    pending = true; controls();
    try {
      const result = await request('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target, milp_seconds: Number(el('milpLimit').value),
          meta_seconds: Number(el('metaLimit').value), seed: Number(el('runSeed').value) }) });
      render(result.job);
      el('runLogs').parentElement.open = true;
    } catch (error) { el('runStatus').textContent = error.message; }
    finally { pending = false; controls(); }
  }
  el('runBoth').onclick = () => start('both');
  el('runMilp').onclick = () => start('milp');
  el('runMeta').onclick = () => start('meta');
  el('cancelRun').onclick = async () => {
    if (!current) return;
    pending = true; controls();
    try { const result = await request(`/api/runs/${current.id}/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); render(result.job); }
    catch (error) { el('runStatus').textContent = error.message; }
    finally { pending = false; controls(); }
  };
  poll();
})();
