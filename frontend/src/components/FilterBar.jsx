import React from 'react';
import { Search, Download, Zap } from 'lucide-react';

export default function FilterBar({
  searchQuery,
  onSearchChange,
  dateFilter,
  onDateFilterChange,
  todayCount,
  signalFilter,
  onSignalFilterChange,
  totalCount,
  bullishCount,
  bearishCount,
  onExportCsv,
}) {
  return (
    <div className="filter-bar">
      {/* Search Input */}
      <div className="search-box">
        <Search size={16} color="var(--text-muted)" />
        <input
          type="text"
          placeholder="Search by Symbol (e.g. RELIANCE, TCS) or Company..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>

      {/* Date Filter: Today vs All */}
      <div className="filter-pills">
        <button
          className={`filter-chip ${dateFilter === 'ALL' ? 'active' : ''}`}
          onClick={() => onDateFilterChange('ALL')}
        >
          All Signals ({totalCount})
        </button>
        <button
          className={`filter-chip today ${dateFilter === 'TODAY' ? 'active today' : ''}`}
          onClick={() => onDateFilterChange('TODAY')}
          title="Filter stocks with crossovers that happened today"
        >
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            <Zap size={13} fill={dateFilter === 'TODAY' ? 'currentColor' : 'none'} />
            Today's Signals ({todayCount})
          </span>
        </button>
      </div>

      {/* Signal Type Filter Chips */}
      <div className="filter-pills">
        <button
          className={`filter-chip ${signalFilter === 'ALL' ? 'active' : ''}`}
          onClick={() => onSignalFilterChange('ALL')}
        >
          All Types
        </button>
        <button
          className={`filter-chip bullish ${signalFilter === 'BULLISH' ? 'active bullish' : ''}`}
          onClick={() => onSignalFilterChange('BULLISH')}
        >
          Bullish ({bullishCount})
        </button>
        <button
          className={`filter-chip bearish ${signalFilter === 'BEARISH' ? 'active bearish' : ''}`}
          onClick={() => onSignalFilterChange('BEARISH')}
        >
          Bearish ({bearishCount})
        </button>
      </div>

      {/* Export Button */}
      {totalCount > 0 && (
        <button
          onClick={onExportCsv}
          className="btn btn-secondary btn-sm"
          title="Download Results as CSV"
        >
          <Download size={14} />
          <span>Export CSV</span>
        </button>
      )}
    </div>
  );
}
