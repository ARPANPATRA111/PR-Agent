import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const TELEGRAM_ID_KEY = 'weekly_agent_telegram_id';

export function getTelegramId(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TELEGRAM_ID_KEY);
}

export function setTelegramId(id: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TELEGRAM_ID_KEY, id);
}

export function clearTelegramId(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TELEGRAM_ID_KEY);
}

export async function fetchAPI<T = any>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_URL}${endpoint}`;
  
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `API error: ${response.status}`);
  }

  return response.json();
}

export async function fetchAPIWithUser<T = any>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const telegramId = getTelegramId();
  if (!telegramId) {
    throw new Error('Please set your Telegram ID in Settings first');
  }
  
  const separator = endpoint.includes('?') ? '&' : '?';
  const urlWithId = `${endpoint}${separator}telegram_id=${telegramId}`;
  
  return fetchAPI<T>(urlWithId, options);
}

export const apiFetch = fetchAPI;

export function formatDate(dateString: string | null | undefined): string {
  if (!dateString) return 'Unknown date';
  const date = new Date(dateString);
  if (isNaN(date.getTime())) return 'Invalid date';
  return date.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}

export function formatDateTime(dateString: string | null | undefined): string {
  if (!dateString) return 'Unknown date';
  const date = new Date(dateString);
  if (isNaN(date.getTime())) return 'Invalid date';
  return date.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

export function formatRelativeTime(dateString: string | null | undefined): string {
  if (!dateString) return 'Unknown';
  const date = new Date(dateString);
  if (isNaN(date.getTime())) return 'Unknown';
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  
  return formatDate(dateString);
}

export const categoryColors: Record<string, string> = {
  coding: 'bg-blue-100 text-blue-800',
  learning: 'bg-green-100 text-green-800',
  debugging: 'bg-red-100 text-red-800',
  research: 'bg-purple-100 text-purple-800',
  meeting: 'bg-yellow-100 text-yellow-800',
  planning: 'bg-orange-100 text-orange-800',
  blockers: 'bg-rose-100 text-rose-800',
  achievement: 'bg-emerald-100 text-emerald-800',
  other: 'bg-gray-100 text-gray-800',
};

export const categoryIcons: Record<string, string> = {
  coding: '💻',
  learning: '📚',
  debugging: '🐛',
  research: '🔍',
  meeting: '👥',
  planning: '📋',
  blockers: '🚧',
  achievement: '🏆',
  other: '📌',
};

export const toneColors: Record<string, string> = {
  friendly: 'bg-amber-100 text-amber-800',
  professional: 'bg-slate-100 text-slate-800',
  technical: 'bg-cyan-100 text-cyan-800',
  casual: 'bg-blue-100 text-blue-800',
  inspirational: 'bg-purple-100 text-purple-800',
};

export function getToneColor(tone: string): string {
  return toneColors[tone] || 'bg-gray-100 text-gray-800';
}

export function getCategoryColor(category: string): string {
  const colors: Record<string, string> = {
    coding: 'bg-blue-500',
    learning: 'bg-green-500',
    project: 'bg-purple-500',
    reflection: 'bg-yellow-500',
    challenge: 'bg-red-500',
    achievement: 'bg-orange-500',
    debugging: 'bg-red-400',
    research: 'bg-indigo-500',
    meeting: 'bg-amber-500',
    planning: 'bg-teal-500',
    blockers: 'bg-rose-500',
    other: 'bg-gray-500',
  };
  return colors[category] || 'bg-gray-500';
}

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) {
    console.error('Failed to copy:', err);
    return false;
  }
}
