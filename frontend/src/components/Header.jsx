import React from 'react';
import { Activity, ShieldCheck, ShieldAlert, Key, LogOut } from 'lucide-react';

export default function Header({ authStatus, onOpenTokenModal, onLogout }) {
  const isConnected = authStatus && authStatus.authenticated;

  return (
    <header className="app-header">
      <div className="brand-section">
        <div className="brand-icon-wrapper">
          <Activity size={24} />
        </div>
        <div>
          <h1 className="brand-title">UPSTOX SEMI-ALGO SCANNER</h1>
          <p className="brand-subtitle">NIFTY 100 + NIFTY 200 • Confirmed 10-Min SMA 6 / SMA 30 Crossovers</p>
        </div>
      </div>

      <div className="header-actions">
        <div className={`status-pill ${isConnected ? 'connected' : 'disconnected'}`}>
          <span className={`status-indicator-dot ${isConnected ? 'connected' : 'disconnected'}`} />
          <span>
            {isConnected
              ? `Upstox: Connected ${authStatus.user_name ? `(${authStatus.user_name})` : ''}`
              : 'Upstox: Disconnected'}
          </span>
        </div>

        {isConnected ? (
          <>
            <button
              onClick={onOpenTokenModal}
              className="btn btn-secondary btn-sm"
              title="Update Upstox Access Token"
            >
              <Key size={14} />
              <span>Token</span>
            </button>
            <button
              onClick={onLogout}
              className="btn btn-secondary btn-sm"
              title="Disconnect Account"
            >
              <LogOut size={14} />
              <span>Logout</span>
            </button>
          </>
        ) : (
          <button
            onClick={onOpenTokenModal}
            className="btn btn-primary btn-sm"
          >
            <Key size={14} />
            <span>Connect Upstox</span>
          </button>
        )}
      </div>
    </header>
  );
}
