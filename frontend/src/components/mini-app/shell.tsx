'use client';

import {
  Activity,
  Bell,
  BookOpen,
  Download,
  Flag,
  Home,
  NotebookPen,
  ReceiptIndianRupee,
  Settings,
  ShieldCheck,
  ShieldAlert,
  Utensils,
} from 'lucide-react';
import type { ComponentType, ReactNode } from 'react';

import type { ScreenName } from '@/lib/public-types';
import { useAuth } from '@/lib/auth';

interface NavigationItem {
  id: ScreenName;
  label: string;
  icon: ComponentType<{ className?: string; 'aria-hidden'?: boolean }>;
}

const navigation: NavigationItem[] = [
  { id: 'home', label: 'Home', icon: Home },
  { id: 'work', label: 'Work', icon: Activity },
  { id: 'notes', label: 'Notes', icon: NotebookPen },
  { id: 'reminders', label: 'Reminders', icon: Bell },
  { id: 'money', label: 'Money', icon: ReceiptIndianRupee },
  { id: 'nutrition', label: 'Nutrition', icon: Utensils },
  { id: 'vault', label: 'Vault', icon: ShieldCheck },
  { id: 'goals', label: 'Goals', icon: Flag },
  { id: 'settings', label: 'Settings', icon: Settings },
  { id: 'export', label: 'Export', icon: Download },
  { id: 'account', label: 'Account', icon: ShieldAlert },
];

export function MiniAppShell({
  activeScreen,
  onNavigate,
  children,
}: {
  activeScreen: ScreenName;
  onNavigate: (screen: ScreenName) => void;
  children: ReactNode;
}) {
  const { user } = useAuth();

  return (
    <div className="min-h-dvh bg-background pb-24 text-foreground">
      <header className="sticky top-0 z-20 border-b bg-background/95 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-sm font-semibold">
              <BookOpen className="h-4 w-4 text-primary" aria-hidden />
              PR-Agent
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {user?.first_name
                ? `Private workspace for ${user.first_name}`
                : 'Private Telegram workspace'}
            </p>
          </div>
          <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">
            Private analytics
          </span>
        </div>
      </header>

      <main
        id="main-content"
        className="mx-auto w-full max-w-5xl px-4 py-6"
      >
        {children}
      </main>

      <nav
        aria-label="Mini App screens"
        className="fixed inset-x-0 bottom-0 z-30 border-t bg-background/98 shadow-[0_-8px_24px_rgba(0,0,0,0.08)]"
      >
        <div className="mx-auto flex max-w-5xl gap-1 overflow-x-auto px-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-2">
          {navigation.map(({ id, label, icon: Icon }) => {
            const selected = activeScreen === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => onNavigate(id)}
                aria-current={selected ? 'page' : undefined}
                aria-label={`Open ${label}`}
                className={`flex min-h-12 min-w-[4.5rem] shrink-0 flex-col items-center justify-center gap-1 rounded-xl px-2 text-[0.7rem] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  selected
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted'
                }`}
              >
                <Icon className="h-4 w-4" aria-hidden />
                {label}
              </button>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
