import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8010';

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 5000,
});

export function getWsUrl() {
  const base = API_BASE.replace(/^http/, 'ws');
  return `${base}/ws/stream`;
}
