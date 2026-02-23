'use client';

import { useState, useEffect, lazy, Suspense } from 'react';
import { Header } from '@/components/layout/header';
import { Sidebar, ViewType } from '@/components/layout/sidebar';
import { useAuth } from '@/lib/auth';
import { LoginForm } from '@/components/auth/login-form';

// Lazy load views for better performance
const Dashboard = lazy(() => import('@/components/dashboard/dashboard').then(m => ({ default: m.Dashboard })));
const EntriesView = lazy(() => import('@/components/entries/entries-view').then(m => ({ default: m.EntriesView })));
const PostsView = lazy(() => import('@/components/posts/posts-view').then(m => ({ default: m.PostsView })));
const SummariesView = lazy(() => import('@/components/summaries/summaries-view').then(m => ({ default: m.SummariesView })));
const PostedReportsView = lazy(() => import('@/components/posted-reports/posted-reports-view').then(m => ({ default: m.PostedReportsView })));
const SettingsView = lazy(() => import('@/components/settings/settings-view').then(m => ({ default: m.SettingsView })));

function LoadingFallback() {
  return (
    <div className="flex items-center justify-center min-h-[50vh]">
      <div className="spinner" />
    </div>
  );
}

export default function Home() {
  const { isAuthenticated, isLoading } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [currentView, setCurrentView] = useState<ViewType>('dashboard');

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <div className="spinner" />
          <span className="text-muted-foreground text-sm">Loading...</span>
        </div>
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
      case 'posted-reports':
        return <PostedReportsView />;
      case 'settings':
        return <SettingsView />;
      default:
        return <Dashboard />;
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <Header onMenuClick={() => setSidebarOpen(!sidebarOpen)} />
      <Sidebar
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        currentView={currentView}
        onViewChange={setCurrentView}
      />
      <main className="lg:pl-64">
        <div className="container py-6 px-4 lg:px-8">
          <Suspense fallback={<LoadingFallback />}>
            {renderView()}
          </Suspense>
        </div>
      </main>
    </div>
  );
}
