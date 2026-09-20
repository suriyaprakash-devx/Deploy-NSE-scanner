import React from 'react';
import { Search, Download, Filter } from 'lucide-react';

export default function FilterBar({
  searchQuery,
  onSearchChange,
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

      {/* Signal Type Filter Chips */}
      <div className="filter-pills">
        <button
          className={`filter-chip ${signalFilter === 'ALL' ? 'active' : ''}`}
          onClick={() => onSignalFilterChange('ALL')}
        >
          All ({totalCount})
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
