// Frontend API Client for FastAPI backend

const BASE_URL = '';

export async function fetchAuthStatus() {
  const res = await fetch(`${BASE_URL}/api/auth/status`);
  if (!res.ok) {
    throw new Error('Failed to fetch auth status');
  }
  return res.json();
}

export async function submitAccessToken(token) {
  const res = await fetch(`${BASE_URL}/api/auth/token`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ access_token: token }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || 'Failed to submit access token');
  }
  return data;
}

export async function logoutUser() {
  const res = await fetch(`${BASE_URL}/api/auth/logout`, {
    method: 'POST',
  });
  return res.json();
}

export async function startScan() {
  const res = await fetch(`${BASE_URL}/api/scanner/run`, {
    method: 'POST',
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || 'Failed to start scanner');
  }
  return data;
}

export async function stopScan() {
  const res = await fetch(`${BASE_URL}/api/scanner/stop`, {
    method: 'POST',
  });
  return res.json();
}

export async function fetchScanStatus() {
  const res = await fetch(`${BASE_URL}/api/scanner/status`);
  if (!res.ok) {
    throw new Error('Failed to fetch scan status');
  }
  return res.json();
}

export async function fetchScanResults() {
  const res = await fetch(`${BASE_URL}/api/scanner/results`);
  if (!res.ok) {
    throw new Error('Failed to fetch scan results');
  }
  return res.json();
}
