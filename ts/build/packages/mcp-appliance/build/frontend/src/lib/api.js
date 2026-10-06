let csrf = '';
let bootstrapToken = '';

export function setCsrf(value='') { csrf = value || ''; }
export function setBootstrapToken(value='') { bootstrapToken = value || ''; }

export async function api(path, options={}) {
  const headers = new Headers(options.headers || {});
  if (csrf && !['GET','HEAD'].includes((options.method || 'GET').toUpperCase())) headers.set('X-CSRF-Token', csrf);
  if (bootstrapToken) headers.set('Authorization', 'Bearer ' + bootstrapToken);
  const r = await fetch(path, { credentials: 'same-origin', ...options, headers });
  let payload;
  const ct = r.headers.get('content-type') || '';
  try { payload = ct.includes('application/json') ? await r.json() : await r.text(); }
  catch { payload = null; }
  if (!r.ok) throw new Error(payload?.error || payload?.message || payload || ('HTTP ' + r.status));
  return payload;
}

export async function json(path, method, body) {
  return api(path, { method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(body ?? {}) });
}
