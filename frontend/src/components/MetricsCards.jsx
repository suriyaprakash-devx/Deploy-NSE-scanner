import React from 'react';
import { ShieldCheck, Clock, BarChart3, TrendingUp, TrendingDown } from 'lucide-react';

export default function MetricsCards({ authStatus, scanStatus, results, lastCompletedAt }) {
  const isConnected = authStatus && authStatus.authenticated;
  
  // Counts
  const totalSignals = results.length;
  const bullishCount = results.filter((r) => r['Signal Type'] === 'BULLISH').length;
  const bearishCount = results.filter((r) => r['Signal Type'] === 'BEARISH').length;

  const formatTime = (isoString) => {
    if (!isoString) return 'Never';
    try {
      const date = new Date(isoString);
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="metrics-grid">
      {/* 1. Upstox Status */}
      <div className="metric-card">
        <div className={`metric-icon-box ${isConnected ? 'green' : 'amber'}`}>
          <ShieldCheck size={24} />
        </div>
        <div className="metric-info">
          <span className="metric-label">Upstox Status</span>
          <span className="metric-value">
            {isConnected ? 'Connected' : 'Disconnected'}
          </span>
          <span className="metric-sub">
            {isConnected ? (authStatus.user_id ? `User: ${authStatus.user_id}` : 'Active Token') : 'Token Required'}
          </span>
        </div>
      </div>

      {/* 2. Last Scan */}
      <div className="metric-card">
        <div className="metric-icon-box cyan">
          <Clock size={24} />
        </div>
        <div className="metric-info">
          <span className="metric-label">Last Scan</span>
          <span className="metric-value">
            {formatTime(lastCompletedAt || scanStatus?.completed_at)}
          </span>
          <span className="metric-sub">
            {scanStatus?.is_running ? 'Scan in progress...' : 'Completed 10-min candles'}
          </span>
        </div>
      </div>

      {/* 3. Stocks Scanned */}
      <div className="metric-card">
        <div className="metric-icon-box purple">
          <BarChart3 size={24} />
        </div>
        <div className="metric-info">
          <span className="metric-label">Stocks Scanned</span>
          <span className="metric-value">
            {scanStatus?.stocks_scanned || 0}
            {scanStatus?.total_stocks > 0 ? ` / ${scanStatus.total_stocks}` : ''}
          </span>
          <span className="metric-sub">NIFTY 100 + NIFTY 200</span>
        </div>
      </div>

      {/* 4. Signals Found */}
      <div className="metric-card">
        <div className="metric-icon-box green">
          <TrendingUp size={24} />
        </div>
        <div className="metric-info">
          <span className="metric-label">Signals Found</span>
          <span className="metric-value">{totalSignals}</span>
          <span className="metric-sub">
            <span style={{ color: 'var(--bullish-neon)' }}>{bullishCount} Bullish</span>
            {' • '}
            <span style={{ color: 'var(--bearish-neon)' }}>{bearishCount} Bearish</span>
          </span>
        </div>
      </div>
    </div>
  );
}
