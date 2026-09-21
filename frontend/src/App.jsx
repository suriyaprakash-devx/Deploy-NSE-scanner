import React, { useState, useEffect, useCallback, useMemo } from 'react';
import Header from './components/Header';
import MetricsCards from './components/MetricsCards';
import ScannerControls from './components/ScannerControls';
import FilterBar from './components/FilterBar';
import ResultsTable from './components/ResultsTable';
import TokenModal from './components/TokenModal';
import {
  fetchAuthStatus,
  submitAccessToken,
  logoutUser,
  startScan,
  stopScan,
  fetchScanStatus,
  fetchScanResults,
} from './api';

export default function App() {
  const [authStatus, setAuthStatus] = useState(null);
  const [scanStatus, setScanStatus] = useState(null);
  const [rawResults, setRawResults] = useState([]);
  const [lastCompletedAt, setLastCompletedAt] = useState(null);

  // Filters & Search
  const [searchQuery, setSearchQuery] = useState('');
  const [dateFilter, setDateFilter] = useState('ALL'); // 'ALL' | 'TODAY'
  const [signalFilter, setSignalFilter] = useState('ALL'); // 'ALL' | 'BULLISH' | 'BEARISH'

  // Modals & UI
  const [isTokenModalOpen, setIsTokenModalOpen] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  // 1. Check Auth Status
  const loadAuthStatus = useCallback(async () => {
    try {
      const data = await fetchAuthStatus();
      setAuthStatus(data);
    } catch (err) {
      console.error('Error loading auth status:', err);
    }
  }, []);

  // 2. Load Scanner Results
  const loadResults = useCallback(async () => {
    try {
      const data = await fetchScanResults();
      setRawResults(data.results || []);
      if (data.completed_at) {
        setLastCompletedAt(data.completed_at);
      }
    } catch (err) {
      console.error('Error loading results:', err);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadAuthStatus();
    loadResults();
  }, [loadAuthStatus, loadResults]);

  // 3. Scanner Status Polling Loop
  useEffect(() => {
    let intervalId = null;

    const checkStatus = async () => {
      try {
        const status = await fetchScanStatus();
        setScanStatus(status);

        // If scan just finished, reload results
        if (!status.is_running && status.stage === 'Completed') {
          loadResults();
        }
      } catch (err) {
        console.error('Error polling scan status:', err);
      }
    };

    // If currently scanning or just launched, poll frequently
    if (scanStatus?.is_running) {
      intervalId = setInterval(checkStatus, 1500);
    } else {
      // Periodic check every 10s
      intervalId = setInterval(checkStatus, 10000);
    }

    return () => clearInterval(intervalId);
  }, [scanStatus?.is_running, loadResults]);

  // Actions
  const handleRunScan = async () => {
    setErrorMessage('');
    try {
      await startScan();
      // Immediately fetch status
      const status = await fetchScanStatus();
      setScanStatus(status);
    } catch (err) {
      setErrorMessage(err.message || 'Failed to start scan.');
    }
  };

  const handleStopScan = async () => {
    try {
      await stopScan();
      const status = await fetchScanStatus();
      setScanStatus(status);
    } catch (err) {
      console.error('Error stopping scan:', err);
    }
  };

  const handleSaveToken = async (token) => {
    const res = await submitAccessToken(token);
    await loadAuthStatus();
    return res;
  };

  const handleLogout = async () => {
    try {
      await logoutUser();
      await loadAuthStatus();
    } catch (err) {
      console.error('Logout error:', err);
    }
  };

  // Today's date string in IST (YYYY-MM-DD)
  const todayStr = useMemo(() => {
    try {
      return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());
    } catch {
      return new Date().toISOString().slice(0, 10);
    }
  }, []);

  // 4. Filtering & Searching
  const todayCount = useMemo(() => {
    return rawResults.filter((r) => r['Crossover Date']?.startsWith(todayStr)).length;
  }, [rawResults, todayStr]);

  const filteredResults = useMemo(() => {
    return rawResults.filter((row) => {
      const matchesSearch =
        searchQuery === '' ||
        row.Symbol?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        row.Company?.toLowerCase().includes(searchQuery.toLowerCase());

      const matchesDate =
        dateFilter === 'ALL' || row['Crossover Date']?.startsWith(todayStr);

      const matchesSignal =
        signalFilter === 'ALL' || row['Signal Type'] === signalFilter;

      return matchesSearch && matchesDate && matchesSignal;
    });
  }, [rawResults, searchQuery, dateFilter, signalFilter, todayStr]);

  // Bullish / Bearish counts based on active date filter
  const dateScopedResults = useMemo(() => {
    return dateFilter === 'ALL'
      ? rawResults
      : rawResults.filter((r) => r['Crossover Date']?.startsWith(todayStr));
  }, [rawResults, dateFilter, todayStr]);

  const bullishCount = dateScopedResults.filter((r) => r['Signal Type'] === 'BULLISH').length;
  const bearishCount = dateScopedResults.filter((r) => r['Signal Type'] === 'BEARISH').length;

  // 5. CSV Export
  const handleExportCsv = () => {
    if (filteredResults.length === 0) return;

    const headers = ['Rank', 'Symbol', 'Company', 'Signal Type', 'Crossover Date', 'Close', 'SMA 6', 'SMA 30'];
    const csvRows = [headers.join(',')];

    filteredResults.forEach((row) => {
      const values = [
        row.Rank,
        `"${row.Symbol}"`,
        `"${row.Company.replace(/"/g, '""')}"`,
        `"${row['Signal Type']}"`,
        `"${row['Crossover Date']}"`,
        row.Close,
        row['SMA 6'],
        row['SMA 30'],
      ];
      csvRows.push(values.join(','));
    });

    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `Upstox_Crossover_Scan_${todayStr}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="app-container">
      {/* Header */}
      <Header
        authStatus={authStatus}
        onOpenTokenModal={() => setIsTokenModalOpen(true)}
        onLogout={handleLogout}
      />

      {/* Top Banner Notice if Disconnected */}
      {authStatus && !authStatus.authenticated && (
        <div className="alert-banner alert-warning">
          <span>
            Upstox is currently disconnected. Click <strong>Connect Upstox</strong> to provide your daily access token and enable scanning.
          </span>
        </div>
      )}

      {/* Metrics Cards */}
      <MetricsCards
        authStatus={authStatus}
        scanStatus={scanStatus}
        results={rawResults}
        lastCompletedAt={lastCompletedAt}
      />

      {/* Scanner Controls */}
      <ScannerControls
        scanStatus={scanStatus}
        onRunScan={handleRunScan}
        onStopScan={handleStopScan}
        onRefreshResults={loadResults}
        isConnected={authStatus?.authenticated}
        onOpenTokenModal={() => setIsTokenModalOpen(true)}
      />

      {/* Filter and Search Bar */}
      <FilterBar
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        dateFilter={dateFilter}
        onDateFilterChange={setDateFilter}
        todayCount={todayCount}
        signalFilter={signalFilter}
        onSignalFilterChange={setSignalFilter}
        totalCount={rawResults.length}
        bullishCount={bullishCount}
        bearishCount={bearishCount}
        onExportCsv={handleExportCsv}
      />

      {/* Results Table */}
      <ResultsTable
        results={filteredResults}
        isLoading={scanStatus?.is_running}
        todayStr={todayStr}
      />

      {/* Token Modal */}
      <TokenModal
        isOpen={isTokenModalOpen}
        onClose={() => setIsTokenModalOpen(false)}
        onSaveToken={handleSaveToken}
      />
    </div>
  );
}
