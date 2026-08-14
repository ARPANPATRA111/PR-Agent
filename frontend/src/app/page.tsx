'use client';

import { useState } from 'react';

import { LoginForm } from '@/components/auth/login-form';
import { MiniAppShell } from '@/components/mini-app/shell';
import {
  AccountDeletionScreen,
  ExportScreen,
  GoalsScreen,
  HomeScreen,
  MoneyScreen,
  NotesScreen,
  NutritionScreen,
  RemindersScreen,
  SettingsScreen,
  VaultScreen,
  WorkLogsScreen,
} from '@/components/mini-app/screens';
import { useAuth } from '@/lib/auth';
import type { ScreenName } from '@/lib/public-types';

function AuthLoading() {
  return (
    <div
      className="flex min-h-dvh items-center justify-center bg-background p-4"
      role="status"
    >
      <div className="rounded-xl border bg-card px-5 py-4 text-sm text-muted-foreground shadow-sm">
        Verifying your Telegram session…
      </div>
    </div>
  );
}

export default function Home() {
  const { isAuthenticated, isLoading } = useAuth();
  const [screen, setScreen] = useState<ScreenName>('home');

  if (isLoading) return <AuthLoading />;
  if (!isAuthenticated) return <LoginForm />;

  const content = {
    home: <HomeScreen onNavigate={setScreen} />,
    work: <WorkLogsScreen />,
    notes: <NotesScreen />,
    reminders: <RemindersScreen />,
    money: <MoneyScreen />,
    nutrition: <NutritionScreen />,
    vault: <VaultScreen />,
    goals: <GoalsScreen />,
    settings: <SettingsScreen onNavigate={setScreen} />,
    export: <ExportScreen />,
    account: <AccountDeletionScreen />,
  } satisfies Record<ScreenName, React.ReactNode>;

  return (
    <MiniAppShell activeScreen={screen} onNavigate={setScreen}>
      {content[screen]}
    </MiniAppShell>
  );
}
