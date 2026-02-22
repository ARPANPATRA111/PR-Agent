'use client';

import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Header } from '@/components/layout/header';
import { Sidebar, ViewType } from '@/components/layout/sidebar';
import { Dashboard } from '@/components/dashboard/dashboard';
import { EntriesView } from '@/components/entries/entries-view';
import { PostsView } from '@/components/posts/posts-view';
import { SummariesView } from '@/components/summaries/summaries-view';
import { PostedReportsView } from '@/components/posted-reports/posted-reports-view';
import { SettingsView } from '@/components/settings/settings-view';
import { useAuth } from '@/lib/auth';
import { LoginForm } from '@/components/auth/login-form';

export default function Home() {
  const { isAuthenticated, isLoading } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [currentView, setCurrentView] = useState<ViewType>('dashboard');
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background animated-gradient">
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="flex flex-col items-center gap-4"
        >
          <div className="w-12 h-12 rounded-full border-2 border-primary border-t-transparent animate-spin" />
          <span className="text-muted-foreground font-medium">Loading...</span>
        </motion.div>
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
    <div className="min-h-screen bg-background animated-gradient">
      {/* Glow orbs for ambient effect */}
      <div className="glow-orb glow-orb-1" aria-hidden="true" />
      <div className="glow-orb glow-orb-2" aria-hidden="true" />
      <div className="glow-orb glow-orb-3" aria-hidden="true" />
      
      {/* Noise texture overlay */}
      <div className="noise-overlay" aria-hidden="true" />
      
      {/* Grid pattern */}
      <div className="fixed inset-0 grid-pattern pointer-events-none" aria-hidden="true" />
      
      <Header
        onMenuClick={() => setSidebarOpen(!sidebarOpen)}
      />
      <Sidebar
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        currentView={currentView}
        onViewChange={setCurrentView}
      />
      <main className="lg:pl-64 relative z-10">
        <AnimatePresence mode="wait">
          <motion.div
            key={currentView}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
            className="container py-6 px-4 lg:px-8"
          >
            {renderView()}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
