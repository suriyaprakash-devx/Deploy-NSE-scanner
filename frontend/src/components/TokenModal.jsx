import React, { useState } from 'react';
import { X, Key, CheckCircle, AlertCircle, ExternalLink } from 'lucide-react';

export default function TokenModal({ isOpen, onClose, onSaveToken }) {
  const [tokenInput, setTokenInput] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!tokenInput.trim()) {
      setErrorMsg('Please enter a valid Upstox Access Token.');
      return;
    }

    setIsSubmitting(true);
    setErrorMsg('');
    setSuccessMsg('');

    try {
      const res = await onSaveToken(tokenInput.trim());
      setSuccessMsg(`Connected successfully! Welcome, ${res.user_name || res.user_id || 'Trader'}.`);
      setTimeout(() => {
        onClose();
        setTokenInput('');
        setSuccessMsg('');
      }, 1500);
    } catch (err) {
      setErrorMsg(err.message || 'Failed to authenticate with Upstox.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div className="brand-icon-wrapper" style={{ width: '36px', height: '36px' }}>
              <Key size={18} />
            </div>
            <div>
              <h2 className="modal-title">Connect Upstox Account</h2>
              <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                Provide your daily Upstox Access Token
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="btn btn-secondary btn-sm"
            style={{ padding: '6px', borderRadius: '50%' }}
          >
            <X size={16} />
          </button>
        </div>

        {errorMsg && (
          <div className="alert-banner alert-danger">
            <AlertCircle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
            <span>{errorMsg}</span>
          </div>
        )}

        {successMsg && (
          <div className="alert-banner" style={{ background: 'var(--bullish-bg)', border: '1px solid var(--bullish-border)', color: '#34d399' }}>
            <CheckCircle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
            <span>{successMsg}</span>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Upstox Access Token</label>
            <textarea
              className="form-input"
              rows={4}
              placeholder="Paste your Upstox access token here (e.g. eyJhbGciOi...)"
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              disabled={isSubmitting}
            />
            <p className="form-help">
              Upstox tokens expire daily at 03:30 AM IST. When your token expires, generate a new token from your Upstox Developer Console or API flow and paste it here.
            </p>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '24px' }}>
            <button
              type="button"
              onClick={onClose}
              className="btn btn-secondary"
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Validating Token...' : 'Connect Upstox'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
