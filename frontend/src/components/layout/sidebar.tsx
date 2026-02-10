'use client';

import Link from 'next/link';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  LayoutDashboard,
  FileText,
  Edit3,
  Calendar,
  Settings,
  X,
  Mic,
  TrendingUp,
  CheckCircle,
} from 'lucide-react';

export type ViewType = 'dashboard' | 'entries' | 'posts' | 'summaries' | 'settings';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  currentView: ViewType;
  onViewChange: (view: ViewType) => void;
}

const navItems = [
  {
    title: 'Dashboard',
    icon: LayoutDashboard,
    view: 'dashboard' as ViewType,
    description: 'Overview and statistics',
  },
  {
    title: 'Voice Entries',
    icon: Mic,
    view: 'entries' as ViewType,
    description: 'View all transcribed entries',
  },
  {
    title: 'LinkedIn Posts',
    icon: Edit3,
    view: 'posts' as ViewType,
    description: 'Generated weekly posts',
  },
  {
    title: 'Daily Summaries',
    icon: Calendar,
    view: 'summaries' as ViewType,
    description: 'Daily reflections',
  },
  {
    title: 'Settings',
    icon: Settings,
    view: 'settings' as ViewType,
    description: 'Configure your agent',
  },
];

export function Sidebar({ isOpen, onClose, currentView, onViewChange }: SidebarProps) {
  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'fixed left-0 top-14 z-40 h-[calc(100vh-3.5rem)] w-64 border-r bg-background transition-transform duration-300 lg:translate-x-0',
          isOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex h-full flex-col">
          {/* Mobile close button */}
          <div className="flex items-center justify-between p-4 lg:hidden">
            <span className="font-semibold">Navigation</span>
            <Button variant="ghost" size="icon" onClick={onClose}>
              <X className="h-5 w-5" />
            </Button>
          </div>

          <ScrollArea className="flex-1 px-3">
            <div className="space-y-1 py-4">
              {navItems.map((item) => (
                <Button
                  key={item.view}
                  variant={currentView === item.view ? 'secondary' : 'ghost'}
                  className={cn(
                    'w-full justify-start gap-3',
                    currentView === item.view && 'bg-secondary'
                  )}
                  onClick={() => {
                    onViewChange(item.view);
                    onClose();
                  }}
                >
                  <item.icon className="h-5 w-5" />
                  <div className="flex flex-col items-start">
                    <span>{item.title}</span>
                  </div>
                </Button>
              ))}
              
              {/* Separate link to Posted Reports page */}
              <div className="pt-4 border-t mt-4">
                <Link href="/posted-reports" onClick={onClose}>
                  <Button
                    variant="ghost"
                    className="w-full justify-start gap-3 text-green-600 hover:text-green-700 hover:bg-green-50 dark:hover:bg-green-950"
                  >
                    <CheckCircle className="h-5 w-5" />
                    <div className="flex flex-col items-start">
                      <span>Posted Reports</span>
                    </div>
                  </Button>
                </Link>
              </div>
            </div>
          </ScrollArea>

          {/* Footer */}
          <div className="border-t p-4">
            <div className="flex items-center gap-3 rounded-lg bg-muted p-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary">
                <TrendingUp className="h-5 w-5 text-primary-foreground" />
              </div>
              <div className="flex-1 space-y-1">
                <p className="text-sm font-medium">Weekly Agent</p>
                <p className="text-xs text-muted-foreground">v1.0.0</p>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
