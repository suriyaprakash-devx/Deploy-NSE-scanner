import React, { useState } from 'react';
import { Play, Square, RefreshCw, Terminal, ChevronDown, ChevronUp, AlertCircle } from 'lucide-react';

export default function ScannerControls({
  scanStatus,
  onRunScan,
  onStopScan,
  onRefreshResults,
  isConnected,
  onOpenTokenModal,
}) {
  const [showLogs, setShowLogs] = useState(false);
  const isScanning = scanStatus?.is_running;

  return (
    <div className="scanner-panel">
      <div className="scanner-panel-header">
        <div>
          <h2 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#ffffff' }}>Scanner Controls</h2>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Run 10-minute SMA 6 / SMA 30 crossover detection across NIFTY constituents
          </p>
        </div>

        <div className="scanner-actions">
          {isScanning ? (
            <button
              onClick={onStopScan}
              className="btn btn-danger"
              title="Stop current scan"
            >
              <Square size={16} fill="currentColor" />
              <span>Stop Scan</span>
            </button>
          ) : (
            <button
              onClick={isConnected ? onRunScan : onOpenTokenModal}
              className="btn btn-primary"
              disabled={isScanning}
            >
              <Play size={16} fill="currentColor" />
              <span>Run Scanner</span>
            </button>
          )}

          <button
            onClick={onRefreshResults}
            className="btn btn-secondary"
            disabled={isScanning}
            title="Reload latest saved scan results"
          >
            <RefreshCw size={15} />
            <span>Refresh Results</span>
          </button>

          <button
            onClick={() => setShowLogs(!showLogs)}
            className="btn btn-secondary btn-sm"
            title="Toggle Live Console Logs"
          >
            <Terminal size={14} />
            <span>Logs</span>
            {showLogs ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>

      {/* Error Notice */}
      {scanStatus?.error_message && (
        <div className="alert-banner alert-danger" style={{ marginTop: '16px' }}>
          <AlertCircle size={18} style={{ flexShrink: 0, marginTop: '2px' }} />
          <div>
            <strong>Scan Notice: </strong>
            <span>{scanStatus.error_message}</span>
          </div>
        </div>
      )}

      {/* Live Scan Progress */}
      {isScanning && (
        <div className="scan-progress-container">
          <div className="scan-progress-info">
            <span style={{ fontWeight: 600, color: '#38bdf8' }}>
              {scanStatus.stage || 'Scanning...'}
              {scanStatus.current_stock ? ` (${scanStatus.current_stock})` : ''}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
              {scanStatus.stocks_scanned} / {scanStatus.total_stocks} ({scanStatus.progress_pct}%)
            </span>
          </div>
          <div className="progress-track">
            <div
              className="progress-fill"
              style={{ width: `${Math.min(scanStatus.progress_pct || 0, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Collapsible Logs Terminal */}
      {showLogs && (
        <div className="log-terminal">
          {scanStatus?.logs && scanStatus.logs.length > 0 ? (
            scanStatus.logs.map((log, index) => (
              <div key={index} className="log-entry">
                {log}
              </div>
            ))
          ) : (
            <div style={{ color: 'var(--text-muted)' }}>No scanner activity logs recorded yet.</div>
          )}
        </div>
      )}
    </div>
  );
}
