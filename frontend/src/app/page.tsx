'use client';

import { useState } from 'react';
import { Header } from '@/components/layout/header';
import { Sidebar, ViewType } from '@/components/layout/sidebar';
import { Dashboard } from '@/components/dashboard/dashboard';
import { EntriesView } from '@/components/entries/entries-view';
import { PostsView } from '@/components/posts/posts-view';
import { SummariesView } from '@/components/summaries/summaries-view';
import { SettingsView } from '@/components/settings/settings-view';
import { useAuth } from '@/lib/auth';
import { LoginForm } from '@/components/auth/login-form';

export default function Home() {
  const { isAuthenticated, isLoading } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [currentView, setCurrentView] = useState<ViewType>('dashboard');

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="animate-pulse text-muted-foreground">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginForm />;
  }

  const renderView = () => {
    switch (currentView) {
      case 'dashboard':
        return <Dashboard />;
      case 'entries':
        return <EntriesView />;
      case 'posts':
        return <PostsView />;
      case 'summaries':
        return <SummariesView />;
      case 'settings':
        return <SettingsView />;
      default:
        return <Dashboard />;
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <Header
        onMenuClick={() => setSidebarOpen(!sidebarOpen)}
      />
      <Sidebar
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        currentView={currentView}
        onViewChange={setCurrentView}
      />
      <main className="lg:pl-64">
        <div className="container py-6">{renderView()}</div>
      </main>
    </div>
  );
}
