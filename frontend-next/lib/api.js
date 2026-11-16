'use client';
import { supabase } from './supabase';

const BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000';

async function authHeaders() {
  const { data } = await supabase.auth.getSession();
  const token = data?.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request(path, { method = 'GET', body, auth = true } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (auth) Object.assign(headers, await authHeaders());
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  base: BASE,
  health: () => request('/api/health', { auth: false }),
  channels: () => request('/api/channels', { auth: false }),
  chat: (history, workspace_id = null) =>
    request('/api/chat', { method: 'POST', body: { history, workspace_id } }),
  generate: (payload) =>
    request('/api/generate', { method: 'POST', body: payload }),
  listWorkspaces: () => request('/api/workspaces'),
  getWorkspace: (id) => request(`/api/workspaces/${id}`),
  deleteWorkspace: (id) => request(`/api/workspaces/${id}`, { method: 'DELETE' }),
  getMessages: (id) => request(`/api/workspaces/${id}/messages`),
  getAgents: (id) => request(`/api/workspaces/${id}/agents`),
  getEmbed: (id) => request(`/api/workspaces/${id}/embed`),
  // Languages the backend can build and converse in. Unauthenticated: the
  // picker is shown before a session exists.
  languages: () => request('/api/languages', { auth: false }),
  assist: (id, message, language = null) =>
    request(`/api/workspaces/${id}/assist`, { method: 'POST', body: { message, language } }),
  agentChat: (id, message, history = [], agent_id = null, locale = null) =>
    request(`/api/workspaces/${id}/agent/chat`, {
      method: 'POST', auth: false, body: { message, history, agent_id, locale },
    }),
  edit: (id, target, instruction, agent_id = null) =>
    request(`/api/workspaces/${id}/edit`, {
      method: 'POST', body: { target, instruction, agent_id },
    }),
  analytics: (id, period = 'week') =>
    request(`/api/workspaces/${id}/analytics?period=${period}`),
  actions: (id) => request(`/api/workspaces/${id}/actions`),
  siteUrl: (assetDir) => `${BASE}/workspaces/${assetDir}/website/index.html`,
  downloadUrl: (id, type) => `${BASE}/api/workspaces/${id}/download/${type}`,
};
