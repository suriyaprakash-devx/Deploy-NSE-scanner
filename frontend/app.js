// NSE Semi-Algo Scanner Frontend Controller

let state = {
  timeframe: '5M',
  universe: 'ALL_NSE',
  scannerRunning: true,
  upstoxConnected: false,
  buySignals: [],
  sellSignals: [],
  selectedOrderSignal: null,
  socket: null,
  reconnectAttempts: 0
};

// --- Web Audio API Synth Alert ---
function playAlertChime(isBuy = true) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(isBuy ? 587.33 : 369.99, ctx.currentTime); // D5 or F#4
    osc.frequency.exponentialRampToValueAtTime(isBuy ? 880 : 220, ctx.currentTime + 0.3);
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.35);
  } catch (e) {
    // Audio context may be restricted before user gesture
  }
}

// --- Toast Notifications ---
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// --- Initialization ---
document.addEventListener('DOMContentLoaded', async () => {
  await fetchInitialStatus();
  await refreshSignals();
  initWebSocket();

  // Periodic safety poll
  setInterval(async () => {
    if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
      await fetchInitialStatus();
      await refreshSignals();
    }
  }, 10000);
});

// --- WebSocket Live Stream ---
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/live`;

  try {
    state.socket = new WebSocket(wsUrl);

    state.socket.onopen = () => {
      state.reconnectAttempts = 0;
      console.log('[WS] Connected to live market feed.');
    };

    state.socket.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        handleWsMessage(msg);
      } catch (err) {
        console.error('[WS] Parse error:', err);
      }
    };

    state.socket.onclose = () => {
      console.warn('[WS] Disconnected. Reconnecting...');
      const delay = Math.min(1000 * Math.pow(1.5, state.reconnectAttempts++), 10000);
      setTimeout(initWebSocket, delay);
    };

    state.socket.onerror = (e) => {
      console.error('[WS] Error:', e);
    };
  } catch (e) {
    console.error('[WS] Initialization failed:', e);
  }
}

function handleWsMessage(msg) {
  switch (msg.type) {
    case 'INIT':
      updateMarketBadge(msg.market_status);
      updateTimeframeUI(msg.timeframe);
      updateUniverseUI(msg.universe);
      updateUpstoxBadge(msg.upstox_connected);
      if (msg.stats) updateStatsUI(msg.stats);
      break;

    case 'HEARTBEAT':
      updateMarketBadge(msg.market_status);
      break;

    case 'NEW_SIGNAL':
      showToast(`⚡ New ${msg.data.direction} signal: ${msg.data.symbol} @ ₹${msg.data.price}`, msg.data.direction.toLowerCase());
      playAlertChime(msg.data.direction === 'BUY');
      refreshSignals();
      break;

    case 'SCAN_PROGRESS':
      updateScanProgress(msg.data);
      break;

    case 'SCAN_COMPLETED':
      updateStatsUI(msg.data);
      refreshSignals();
      break;

    case 'TIMEFRAME_CHANGED':
      updateTimeframeUI(msg.timeframe);
      refreshSignals();
      break;

    case 'UNIVERSE_CHANGED':
      updateUniverseUI(msg.universe);
      break;

    case 'ORDER_PLACED':
      showToast(`✅ Manual order executed: ${msg.symbol} (${msg.direction})`, 'buy');
      refreshSignals();
      loadOrderHistory();
      break;

    case 'SIGNAL_STATUS_UPDATED':
      refreshSignals();
      break;
  }
}

// --- API Calls ---
async function fetchInitialStatus() {
  try {
    const res = await fetch('/api/scanner/status');
    const data = await res.json();
    if (data.status) {
      state.scannerRunning = data.is_running;
      state.timeframe = data.status.selected_timeframe;
      state.universe = data.status.universe_name;
      state.upstoxConnected = data.status.upstox_connected;

      updateMarketBadge(data.market);
      updateTimeframeUI(state.timeframe);
      updateUniverseUI(state.universe);
      updateUpstoxBadge(state.upstoxConnected);
      updateStatsUI(data.status);
      updateScannerBtnUI(state.scannerRunning);
    }
  } catch (e) {
    console.error('Failed to fetch scanner status:', e);
  }
}

async function refreshSignals() {
  try {
    const [buyRes, sellRes] = await Promise.all([
      fetch(`/api/signals/buy?timeframe=${state.timeframe}`),
      fetch(`/api/signals/sell?timeframe=${state.timeframe}`)
    ]);

    const buyData = await buyRes.json();
    const sellData = await sellRes.json();

    state.buySignals = buyData.signals || [];
    state.sellSignals = sellData.signals || [];

    renderSignalsTable('BUY', state.buySignals, 'buySignalsBody', 'buyCount');
    renderSignalsTable('SELL', state.sellSignals, 'sellSignalsBody', 'sellCount');
  } catch (e) {
    console.error('Failed to load signals:', e);
  }
}

// --- UI Updaters ---
function updateMarketBadge(status) {
  const badge = document.getElementById('marketBadge');
  const label = document.getElementById('marketStatusText');
  if (!badge || !label) return;

  status = (status || 'CLOSED').toUpperCase();
  label.textContent = `MARKET: ${status}`;

  badge.className = 'badge-pill market-pill';
  if (status === 'OPEN') {
    badge.classList.add('open');
  } else {
    badge.classList.add('closed');
  }
}

function updateUpstoxBadge(connected) {
  const badge = document.getElementById('upstoxBadge');
  const label = document.getElementById('upstoxStatusText');
  if (!badge || !label) return;

  state.upstoxConnected = connected;
  badge.className = 'badge-pill upstox-pill';

  if (connected) {
    badge.classList.add('connected');
    label.textContent = 'Upstox: Connected';
  } else {
    badge.classList.add('disconnected');
    label.textContent = 'Upstox: Disconnected';
  }
}

function updateTimeframeUI(tf) {
  state.timeframe = tf;
  const btn5m = document.getElementById('tf5mBtn');
  const btn10m = document.getElementById('tf10mBtn');

  if (tf === '10M') {
    btn10m.classList.add('active');
    btn5m.classList.remove('active');
  } else {
    btn5m.classList.add('active');
    btn10m.classList.remove('active');
  }
}

function updateUniverseUI(u) {
  state.universe = u;
  const select = document.getElementById('universeSelect');
  if (select) select.value = u;
}

function updateScannerBtnUI(running) {
  const btn = document.getElementById('toggleScannerBtn');
  if (!btn) return;

  if (running) {
    btn.textContent = 'Pause';
    btn.className = 'btn btn-secondary';
  } else {
    btn.textContent = 'Start';
    btn.className = 'btn btn-primary';
  }
}

function updateStatsUI(stats) {
  document.getElementById('statLastScan').textContent = stats.last_scan_time ? stats.last_scan_time.split(' ')[1] : '--:--:--';
  document.getElementById('statDuration').textContent = `Cycle: ${stats.last_scan_duration_sec || 0.0}s`;
  document.getElementById('statScanned').textContent = `${stats.stocks_scanned || 0} / ${stats.total_universe || 0}`;

  const pct = stats.total_universe > 0 ? Math.round((stats.stocks_scanned / stats.total_universe) * 100) : 0;
  document.getElementById('statProgressPct').textContent = `${pct}%`;

  document.getElementById('statSuccess').textContent = stats.successful_scans || 0;
  document.getElementById('statFailed').textContent = stats.failed_scans || 0;
  document.getElementById('statSignalsToday').textContent = stats.signals_detected_today || 0;

  const engineStatus = document.getElementById('statEngineStatus');
  engineStatus.textContent = stats.is_running ? 'Active' : 'Paused';
  engineStatus.className = `stat-value status-text ${stats.is_running ? 'text-success' : 'text-danger'}`;

  document.getElementById('statMessage').textContent = stats.status_message || 'Scanner running...';
}

function updateScanProgress(prog) {
  document.getElementById('statScanned').textContent = `${prog.stocks_scanned} / ${prog.total_universe}`;
  const pct = prog.total_universe > 0 ? Math.round((prog.stocks_scanned / prog.total_universe) * 100) : 0;
  document.getElementById('statProgressPct').textContent = `${pct}%`;
  document.getElementById('statSuccess').textContent = prog.successful_scans;
  document.getElementById('statFailed').textContent = prog.failed_scans;
}

// --- Render Signals Tables ---
function renderSignalsTable(direction, signals, bodyId, countId) {
  const tbody = document.getElementById(bodyId);
  const countBadge = document.getElementById(countId);
  if (!tbody) return;

  countBadge.textContent = signals.length;

  if (signals.length === 0) {
    tbody.innerHTML = `
      <tr class="empty-row">
        <td colspan="8">No ${direction} crossover signals confirmed on completed ${state.timeframe} candles.</td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = signals.map((sig) => {
    const isBuy = direction === 'BUY';
    const actionClass = isBuy ? 'btn-buy-action' : 'btn-sell-action';
    const actionLabel = isBuy ? 'Manual BUY' : 'Manual SELL';
    const isPending = sig.status === 'PENDING';

    let actionButtons = '';
    if (isPending) {
      actionButtons = `
        <div class="action-buttons">
          <button class="btn ${actionClass} btn-sm" onclick='openOrderApproval(${JSON.stringify(sig)})'>
            ${actionLabel}
          </button>
          <button class="btn btn-secondary btn-sm" onclick="rejectSignal(${sig.id})" title="Reject Signal">
            ✕
          </button>
        </div>
      `;
    } else if (sig.status === 'ORDER_PLACED') {
      actionButtons = `<span class="status-badge status-approved">ORDER PLACED</span>`;
    } else {
      actionButtons = `<span class="status-badge status-rejected">REJECTED</span>`;
    }

    const timeFormatted = sig.crossover_time_str ? sig.crossover_time_str.split(' ')[1] : '--:--';

    return `
      <tr>
        <td class="rank-cell">#${sig.rank}</td>
        <td class="symbol-cell">${sig.symbol}</td>
        <td>₹${sig.crossover_price.toFixed(2)}</td>
        <td class="text-accent">${sig.ema6.toFixed(2)}</td>
        <td>${sig.ema30.toFixed(2)}</td>
        <td>${timeFormatted}</td>
        <td><span class="status-badge status-pending">${sig.timeframe}</span></td>
        <td style="text-align: right;">${actionButtons}</td>
      </tr>
    `;
  }).join('');
}

// --- Actions: Controls & Modals ---
async function setTimeframe(tf) {
  if (tf === state.timeframe) return;
  updateTimeframeUI(tf);
  try {
    await fetch('/api/settings/timeframe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ timeframe: tf })
    });
    showToast(`Timeframe changed to ${tf}`, 'info');
    await refreshSignals();
  } catch (e) {
    showToast('Failed to switch timeframe', 'sell');
  }
}

async function setUniverse(u) {
  try {
    await fetch('/api/settings/universe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ universe: u })
    });
    showToast(`Active universe set to ${u}`, 'info');
  } catch (e) {
    showToast('Failed to update universe', 'sell');
  }
}

async function toggleScanner() {
  const endpoint = state.scannerRunning ? '/api/scanner/stop' : '/api/scanner/start';
  try {
    const res = await fetch(endpoint, { method: 'POST' });
    const data = await res.json();
    state.scannerRunning = data.is_running;
    updateScannerBtnUI(state.scannerRunning);
    showToast(state.scannerRunning ? 'Scanner resumed' : 'Scanner paused', 'info');
  } catch (e) {
    showToast('Failed to toggle scanner', 'sell');
  }
}

async function triggerScanNow() {
  if (!state.upstoxConnected) {
    showToast('Please connect your Upstox Access Token first', 'sell');
    openUpstoxModal();
    return;
  }
  try {
    await fetch('/api/scanner/scan-now', { method: 'POST' });
    showToast('Immediate scan cycle triggered...', 'info');
  } catch (e) {
    showToast('Scan initiation failed', 'sell');
  }
}

async function rejectSignal(signalId) {
  try {
    await fetch(`/api/signals/${signalId}/reject`, { method: 'POST' });
    showToast('Signal rejected and archived.', 'info');
    await refreshSignals();
  } catch (e) {
    showToast('Failed to reject signal', 'sell');
  }
}

// --- View Switching ---
function switchView(view) {
  const sigView = document.getElementById('signalsView');
  const ordView = document.getElementById('ordersView');
  const tabs = document.querySelectorAll('.tab-link');

  tabs.forEach(t => t.classList.remove('active'));

  if (view === 'signals') {
    sigView.classList.remove('hidden');
    ordView.classList.add('hidden');
    tabs[0].classList.add('active');
    refreshSignals();
  } else {
    sigView.classList.add('hidden');
    ordView.classList.remove('hidden');
    tabs[1].classList.add('active');
    loadOrderHistory();
  }
}

// --- Order Execution Audit Log ---
async function loadOrderHistory() {
  try {
    const res = await fetch('/api/orders/history');
    const data = await res.json();
    const tbody = document.getElementById('ordersHistoryBody');
    if (!tbody) return;

    if (!data.orders || data.orders.length === 0) {
      tbody.innerHTML = `
        <tr class="empty-row">
          <td colspan="10">No orders placed through semi-algo manual approval yet.</td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = data.orders.map(o => `
      <tr>
        <td>#${o.id}</td>
        <td>${o.created_at}</td>
        <td class="symbol-cell">${o.symbol}</td>
        <td><strong class="${o.direction === 'BUY' ? 'text-success' : 'text-danger'}">${o.direction}</strong></td>
        <td>${o.quantity}</td>
        <td>${o.order_type}</td>
        <td>${o.product === 'I' ? 'INTRADAY' : 'DELIVERY'}</td>
        <td>₹${o.price.toFixed(2)}</td>
        <td class="rank-cell">${o.order_id || '--'}</td>
        <td><span class="status-badge ${o.status === 'SUCCESS' ? 'status-approved' : 'status-rejected'}">${o.status}</span></td>
      </tr>
    `).join('');
  } catch (e) {
    console.error('Failed to load order history:', e);
  }
}

// --- Manual Order Approval Modal (Semi-Algo Requirement) ---
function openOrderApproval(signal) {
  state.selectedOrderSignal = signal;

  document.getElementById('modalStock').textContent = signal.symbol;
  const sideEl = document.getElementById('modalSide');
  sideEl.textContent = signal.direction;
  sideEl.className = `value ${signal.direction === 'BUY' ? 'text-success' : 'text-danger'}`;

  document.getElementById('modalSignalPrice').textContent = `₹${signal.crossover_price.toFixed(2)}`;
  document.getElementById('modalTimeframe').textContent = signal.timeframe;

  document.getElementById('orderQty').value = 1;
  document.getElementById('orderType').value = 'MARKET';
  document.getElementById('orderLimitPrice').value = signal.crossover_price.toFixed(2);
  toggleLimitPriceField('MARKET');
  recalcOrderTotal();

  document.getElementById('orderModal').classList.remove('hidden');
}

function closeOrderModal() {
  document.getElementById('orderModal').classList.add('hidden');
  state.selectedOrderSignal = null;
}

function toggleLimitPriceField(orderType) {
  const group = document.getElementById('limitPriceGroup');
  if (orderType === 'LIMIT') {
    group.style.display = 'flex';
  } else {
    group.style.display = 'none';
  }
  recalcOrderTotal();
}

function recalcOrderTotal() {
  if (!state.selectedOrderSignal) return;
  const qty = parseInt(document.getElementById('orderQty').value, 10) || 1;
  const orderType = document.getElementById('orderType').value;
  let price = state.selectedOrderSignal.crossover_price;

  if (orderType === 'LIMIT') {
    price = parseFloat(document.getElementById('orderLimitPrice').value) || price;
  }

  const total = qty * price;
  document.getElementById('orderEstValue').textContent = `₹${total.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

async function submitManualOrder() {
  if (!state.selectedOrderSignal) return;
  const sig = state.selectedOrderSignal;

  const qty = parseInt(document.getElementById('orderQty').value, 10);
  const orderType = document.getElementById('orderType').value;
  const product = document.getElementById('orderProduct').value;
  const price = orderType === 'LIMIT' ? parseFloat(document.getElementById('orderLimitPrice').value) : 0.0;

  const btn = document.getElementById('confirmOrderBtn');
  btn.disabled = true;
  btn.textContent = 'Sending to Upstox...';

  try {
    const res = await fetch('/api/orders/place', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        signal_id: sig.id,
        symbol: sig.symbol,
        instrument_key: sig.instrument_key,
        direction: sig.direction,
        quantity: qty,
        order_type: orderType,
        price: price,
        product: product
      })
    });

    const data = await res.json();
    if (res.ok) {
      showToast(`Order placed successfully! Upstox ID: ${data.order_id}`, 'buy');
      closeOrderModal();
      await refreshSignals();
    } else {
      showToast(`Order failed: ${data.detail || 'Rejected by broker'}`, 'sell');
    }
  } catch (err) {
    showToast(`Order submission error: ${err.message}`, 'sell');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Confirm & Execute via Upstox';
  }
}

// --- Upstox Modal ---
async function openUpstoxModal() {
  const modal = document.getElementById('upstoxModal');
  const info = document.getElementById('tokenStatusInfo');
  modal.classList.remove('hidden');

  try {
    const res = await fetch('/api/upstox/status');
    const data = await res.json();
    if (data.configured) {
      info.innerHTML = `<span class="text-success">Current Token: ${data.masked_token} (Active)</span>`;
    } else {
      info.innerHTML = `<span class="text-danger">No token configured. Scanner cannot fetch live candles.</span>`;
    }
  } catch (e) {
    info.textContent = '';
  }
}

function closeUpstoxModal() {
  document.getElementById('upstoxModal').classList.add('hidden');
}

async function saveUpstoxToken() {
  const input = document.getElementById('upstoxTokenInput');
  const token = input.value.trim();

  if (!token) {
    showToast('Please enter a valid Upstox Access Token', 'sell');
    return;
  }

  try {
    const res = await fetch('/api/upstox/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ access_token: token })
    });

    const data = await res.json();
    if (res.ok) {
      showToast(`Connected to Upstox account: ${data.account_name}`, 'buy');
      updateUpstoxBadge(true);
      closeUpstoxModal();
      input.value = '';
    } else {
      showToast(`Connection failed: ${data.detail}`, 'sell');
    }
  } catch (err) {
    showToast(`Error connecting to Upstox: ${err.message}`, 'sell');
  }
}

async function disconnectUpstox() {
  try {
    await fetch('/api/upstox/disconnect', { method: 'POST' });
    showToast('Disconnected from Upstox', 'info');
    updateUpstoxBadge(false);
    closeUpstoxModal();
  } catch (e) {
    showToast('Disconnect error', 'sell');
  }
}
