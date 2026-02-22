'use client';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { motion } from 'framer-motion';
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
  Sparkles,
} from 'lucide-react';

export type ViewType = 'dashboard' | 'entries' | 'posts' | 'summaries' | 'posted-reports' | 'settings';

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
    description: 'Overview',
  },
  {
    title: 'Voice Entries',
    icon: Mic,
    view: 'entries' as ViewType,
    description: 'Transcriptions',
  },
  {
    title: 'LinkedIn Posts',
    icon: Edit3,
    view: 'posts' as ViewType,
    description: 'Generated drafts',
  },
  {
    title: 'Daily Summaries',
    icon: Calendar,
    view: 'summaries' as ViewType,
    description: 'Reflections',
  },
  {
    title: 'Posted Reports',
    icon: CheckCircle,
    view: 'posted-reports' as ViewType,
    description: 'Published',
  },
  {
    title: 'Settings',
    icon: Settings,
    view: 'settings' as ViewType,
    description: 'Configure',
  },
];

export function Sidebar({ isOpen, onClose, currentView, onViewChange }: SidebarProps) {
  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-40 bg-background/60 backdrop-blur-md lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'fixed left-0 top-14 z-40 h-[calc(100vh-3.5rem)] w-64 border-r border-border/50 bg-card/50 backdrop-blur-xl transition-transform duration-300 lg:translate-x-0',
          isOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex h-full flex-col">
          {/* Mobile close button */}
          <div className="flex items-center justify-between p-4 lg:hidden">
            <span className="font-semibold bg-clip-text text-transparent bg-gradient-to-r from-primary to-accent">Navigation</span>
            <Button variant="ghost" size="icon" onClick={onClose} className="hover:bg-muted">
              <X className="h-5 w-5" />
            </Button>
          </div>

          <ScrollArea className="flex-1 px-3">
            <div className="space-y-1 py-4">
              {navItems.map((item, index) => {
                const isActive = currentView === item.view;
                return (
                  <motion.div
                    key={item.view}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: index * 0.05 }}
                  >
                    <button
                      className={cn(
                        'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200 group',
                        isActive 
                          ? 'bg-primary/10 text-primary' 
                          : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
                      )}
                      onClick={() => {
                        onViewChange(item.view);
                        onClose();
                      }}
                    >
                      <div className={cn(
                        'flex items-center justify-center w-9 h-9 rounded-lg transition-all duration-200',
                        isActive 
                          ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/25' 
                          : 'bg-muted/50 group-hover:bg-muted'
                      )}>
                        <item.icon className="h-4 w-4" />
                      </div>
                      <div className="flex flex-col items-start flex-1 min-w-0">
                        <span className="text-sm font-medium truncate">{item.title}</span>
                        <span className="text-xs text-muted-foreground truncate">{item.description}</span>
                      </div>
                      {isActive && (
                        <motion.div 
                          layoutId="activeIndicator"
                          className="w-1.5 h-8 bg-primary rounded-full"
                          transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                        />
                      )}
                    </button>
                  </motion.div>
                );
              })}
            </div>
          </ScrollArea>

          {/* Footer - Status indicator */}
          <div className="border-t border-border/50 p-4">
            <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-card to-muted/50 p-4 border border-border/30">
              {/* Decorative gradient */}
              <div className="absolute -top-12 -right-12 w-24 h-24 bg-primary/10 rounded-full blur-2xl" />
              
              <div className="relative flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-primary/60 shadow-lg shadow-primary/20">
                  <Sparkles className="h-5 w-5 text-primary-foreground" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold truncate">Weekly Agent</p>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                    </span>
                    <span className="text-xs text-muted-foreground font-mono">Online</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
