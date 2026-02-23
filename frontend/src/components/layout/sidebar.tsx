'use client';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  LayoutDashboard,
  FileText,
  Edit3,
  Calendar,
  Settings,
  X,
  Mic,
  CheckCircle,
} from 'lucide-react';

export type ViewType = 'dashboard' | 'entries' | 'posts' | 'summaries' | 'posted-reports' | 'settings';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  currentView: ViewType;
  onViewChange: (view: ViewType) => void;
}

const navItems = [
  { title: 'Dashboard', icon: LayoutDashboard, view: 'dashboard' as ViewType },
  { title: 'Voice Entries', icon: Mic, view: 'entries' as ViewType },
  { title: 'LinkedIn Posts', icon: Edit3, view: 'posts' as ViewType },
  { title: 'Daily Summaries', icon: Calendar, view: 'summaries' as ViewType },
  { title: 'Posted Reports', icon: CheckCircle, view: 'posted-reports' as ViewType },
  { title: 'Settings', icon: Settings, view: 'settings' as ViewType },
];

export function Sidebar({ isOpen, onClose, currentView, onViewChange }: SidebarProps) {
  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'fixed left-0 top-14 z-40 h-[calc(100vh-3.5rem)] w-64 border-r bg-card transition-transform duration-200 lg:translate-x-0',
          isOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex h-full flex-col">
          {/* Mobile header */}
          <div className="flex items-center justify-between p-4 border-b lg:hidden">
            <span className="font-semibold text-primary">Navigation</span>
            <Button variant="ghost" size="icon" onClick={onClose}>
              <X className="h-5 w-5" />
            </Button>
          </div>

          {/* Navigation */}
          <nav className="flex-1 overflow-y-auto p-3">
            <div className="space-y-1">
              {navItems.map((item) => {
                const isActive = currentView === item.view;
                return (
                  <button
                    key={item.view}
                    className={cn(
                      'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                      isActive 
                        ? 'bg-primary/10 text-primary' 
                        : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                    )}
                    onClick={() => {
                      onViewChange(item.view);
                      onClose();
                    }}
                  >
                    <item.icon className={cn('h-5 w-5', isActive && 'text-primary')} />
                    {item.title}
                  </button>
                );
              })}
            </div>
          </nav>

          {/* Footer */}
          <div className="border-t p-4">
            <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/50">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground font-semibold">
                W
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium">Weekly Agent</p>
                <div className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-green-500"></span>
                  <span className="text-xs text-muted-foreground">Online</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
