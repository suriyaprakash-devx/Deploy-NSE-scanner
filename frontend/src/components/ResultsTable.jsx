import React, { useState } from 'react';
import { ArrowUpRight, ArrowDownRight, ArrowUpDown, Inbox } from 'lucide-react';

export default function ResultsTable({ results, isLoading, todayStr }) {
  const [sortField, setSortField] = useState('Rank');
  const [sortDirection, setSortDirection] = useState('asc'); // 'asc' or 'desc'

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };

  const sortedResults = [...results].sort((a, b) => {
    let valA = a[sortField];
    let valB = b[sortField];

    if (sortField === 'Rank' || sortField === 'Close' || sortField === 'SMA 6' || sortField === 'SMA 30') {
      valA = parseFloat(valA) || 0;
      valB = parseFloat(valB) || 0;
    }

    if (valA < valB) return sortDirection === 'asc' ? -1 : 1;
    if (valA > valB) return sortDirection === 'asc' ? 1 : -1;
    return 0;
  });

  return (
    <div className="table-wrapper">
      <div className="table-scroll">
        <table className="results-table">
          <thead>
            <tr>
              <th onClick={() => handleSort('Rank')} style={{ cursor: 'pointer' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span>Rank</span>
                  <ArrowUpDown size={12} />
                </div>
              </th>
              <th onClick={() => handleSort('Symbol')} style={{ cursor: 'pointer' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span>Symbol</span>
                  <ArrowUpDown size={12} />
                </div>
              </th>
              <th>Company</th>
              <th onClick={() => handleSort('Signal Type')} style={{ cursor: 'pointer' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span>Signal Type</span>
                  <ArrowUpDown size={12} />
                </div>
              </th>
              <th onClick={() => handleSort('Crossover Date')} style={{ cursor: 'pointer' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span>Crossover Date</span>
                  <ArrowUpDown size={12} />
                </div>
              </th>
              <th onClick={() => handleSort('Close')} style={{ cursor: 'pointer' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span>Close (₹)</span>
                  <ArrowUpDown size={12} />
                </div>
              </th>
              <th onClick={() => handleSort('SMA 6')} style={{ cursor: 'pointer' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span>SMA 6</span>
                  <ArrowUpDown size={12} />
                </div>
              </th>
              <th onClick={() => handleSort('SMA 30')} style={{ cursor: 'pointer' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span>SMA 30</span>
                  <ArrowUpDown size={12} />
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedResults.length > 0 ? (
              sortedResults.map((item, idx) => {
                const isBullish = item['Signal Type'] === 'BULLISH';
                return (
                  <tr key={`${item.Symbol}-${idx}`}>
                    <td>
                      <span className="rank-badge">#{item.Rank}</span>
                    </td>
                    <td>
                      <span className="symbol-cell">{item.Symbol}</span>
                    </td>
                    <td>
                      <span className="company-cell" title={item.Company}>
                        {item.Company}
                      </span>
                    </td>
                    <td>
                      <span className={`signal-badge ${isBullish ? 'bullish' : 'bearish'}`}>
                        {isBullish ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                        <span>{item['Signal Type']}</span>
                      </span>
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem', whiteSpace: 'nowrap' }}>
                      {todayStr && item['Crossover Date']?.startsWith(todayStr) && (
                        <span className="today-badge">TODAY</span>
                      )}
                      <span>{item['Crossover Date']}</span>
                    </td>
                    <td>
                      <span className="price-num">₹{item.Close}</span>
                    </td>
                    <td>
                      <span className="price-num" style={{ color: '#93c5fd' }}>
                        {item['SMA 6']}
                      </span>
                    </td>
                    <td>
                      <span className="price-num" style={{ color: '#c4b5fd' }}>
                        {item['SMA 30']}
                      </span>
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={8}>
                  <div className="empty-state">
                    <Inbox className="empty-state-icon" />
                    <h3 style={{ fontSize: '1rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                      No Crossover Signals Found
                    </h3>
                    <p style={{ fontSize: '0.82rem' }}>
                      Click <strong>Run Scanner</strong> to fetch daily candles from Upstox and detect active SMA crossovers.
                    </p>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
