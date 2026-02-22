'use client';

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Mic,
  FileText,
  Calendar,
  TrendingUp,
  Zap,
  Target,
  BookOpen,
  Code,
  Lightbulb,
  Trophy,
  AlertTriangle,
  ArrowRight,
  Sparkles,
  Activity,
  BarChart3,
  Brain,
  Flame,
  MessageSquare,
  RefreshCw,
  Rocket,
  Star,
} from 'lucide-react';
import { fetchAPIWithUser, getTelegramId, formatRelativeTime, getCategoryColor } from '@/lib/utils';

interface StatsData {
  total_entries: number;
  total_posts: number;
  total_summaries: number;
  entries_this_week: number;
  last_entry_date: string | null;
  categories: Record<string, number>;
  streak?: number;
}

interface Entry {
  id: number;
  date: string;
  category: string;
  raw_text: string;
  created_at: string;
}

const categoryIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  coding: Code,
  learning: BookOpen,
  project: Target,
  reflection: Lightbulb,
  challenge: AlertTriangle,
  achievement: Trophy,
  debugging: AlertTriangle,
  research: Brain,
  meeting: MessageSquare,
  planning: Target,
  blockers: AlertTriangle,
  other: Zap,
};

const categoryGradients: Record<string, string> = {
  coding: 'from-blue-500 to-cyan-500',
  learning: 'from-purple-500 to-pink-500',
  project: 'from-green-500 to-emerald-500',
  achievement: 'from-yellow-500 to-orange-500',
  debugging: 'from-red-500 to-rose-500',
  research: 'from-indigo-500 to-violet-500',
  meeting: 'from-teal-500 to-cyan-500',
  planning: 'from-amber-500 to-yellow-500',
  blockers: 'from-rose-500 to-red-500',
  other: 'from-gray-500 to-slate-500',
};

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.1 },
  },
};

const cardVariants = {
  hidden: { opacity: 0, y: 20, scale: 0.95 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { type: 'spring' as const, stiffness: 100, damping: 15 },
  },
};

const statVariants = {
  hidden: { opacity: 0, scale: 0.8 },
  visible: (i: number) => ({
    opacity: 1,
    scale: 1,
    transition: { delay: i * 0.1, type: 'spring' as const, stiffness: 200, damping: 20 },
  }),
};

export function Dashboard() {
  const [stats, setStats] = useState<StatsData | null>(null);
  const [recentEntries, setRecentEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = async () => {
    try {
      const telegramId = getTelegramId();
      if (!telegramId) {
        setError('Please set your Telegram ID in Settings first');
        setLoading(false);
        return;
      }
      
      const [statsData, entriesData] = await Promise.all([
        fetchAPIWithUser('/api/stats'),
        fetchAPIWithUser('/api/entries?limit=5'),
      ]);
      setStats(statsData);
      setRecentEntries(entriesData.entries || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  if (loading) {
    return <DashboardSkeleton />;
  }

  if (error) {
    return (
      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex h-full items-center justify-center p-8"
      >
        <Card className="w-full max-w-md premium-card border-destructive/30">
          <CardHeader>
            <CardTitle className="text-destructive flex items-center gap-2">
              <AlertTriangle className="h-5 w-5" />
              Error
            </CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button 
              onClick={handleRefresh} 
              variant="outline" 
              className="w-full btn-magnetic rounded-xl"
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Try Again
            </Button>
          </CardContent>
        </Card>
      </motion.div>
    );
  }

  const totalCategories = stats?.categories 
    ? Object.values(stats.categories).reduce((a, b) => a + b, 0) 
    : 0;

  return (
    <div className="space-y-8 pb-8">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-card via-card to-muted/30 p-8 border border-border/30"
      >
        <div className="absolute -top-32 -right-32 w-64 h-64 bg-primary/20 rounded-full blur-3xl" />
        <div className="absolute -bottom-32 -left-32 w-64 h-64 bg-accent/15 rounded-full blur-3xl" />
        
        <div className="relative flex flex-col md:flex-row md:items-center md:justify-between gap-6">
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <motion.div 
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', stiffness: 200, damping: 15 }}
                className="p-3 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/20"
              >
                <Rocket className="h-7 w-7 text-primary" />
              </motion.div>
              <div>
                <h1 className="text-3xl md:text-4xl font-bold tracking-tight">
                  <span className="gradient-text">Dashboard</span>
                </h1>
                <p className="text-muted-foreground text-sm">
                  Your weekly progress at a glance
                </p>
              </div>
            </div>
          </div>
          
          <Button 
            onClick={handleRefresh} 
            variant="outline" 
            size="sm"
            disabled={refreshing}
            className="w-fit btn-magnetic rounded-xl border-border/50 hover:border-primary/50"
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </motion.div>

      <motion.div 
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        className="grid gap-4 md:grid-cols-2 lg:grid-cols-4"
      >
        {[
          {
            title: "Voice Entries",
            value: stats?.total_entries || 0,
            description: "Total transcribed notes",
            icon: Mic,
            trend: stats?.entries_this_week,
            trendLabel: "this week",
            gradient: "from-blue-500 to-cyan-500"
          },
          {
            title: "Weekly Posts",
            value: stats?.total_posts || 0,
            description: "LinkedIn posts generated",
            icon: FileText,
            gradient: "from-purple-500 to-pink-500"
          },
          {
            title: "Daily Summaries",
            value: stats?.total_summaries || 0,
            description: "Reflections created",
            icon: Calendar,
            gradient: "from-green-500 to-emerald-500"
          },
          {
            title: "Current Streak",
            value: stats?.streak || 0,
            description: stats?.last_entry_date ? formatRelativeTime(stats.last_entry_date) : 'No entries yet',
            icon: Flame,
            gradient: "from-orange-500 to-red-500",
            isStreak: true
          }
        ].map((stat, index) => (
          <motion.div key={stat.title} custom={index} variants={statVariants}>
            <StatsCard {...stat} />
          </motion.div>
        ))}
      </motion.div>

      <div className="grid gap-6 lg:grid-cols-3">
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.4 }}
          className="lg:col-span-2"
        >
          <Card className="premium-card h-full overflow-hidden">
            <CardHeader className="pb-3 border-b border-border/30">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-xl bg-primary/10 border border-primary/20">
                    <Activity className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <CardTitle className="text-lg">Recent Activity</CardTitle>
                    <CardDescription className="text-xs">Your latest voice entries</CardDescription>
                  </div>
                </div>
                <Button variant="ghost" size="sm" className="text-primary text-xs rounded-lg">
                  View All
                  <ArrowRight className="ml-1 h-3.5 w-3.5" />
                </Button>
              </div>
            </CardHeader>
            <CardContent className="pt-4">
              <ScrollArea className="h-[380px] pr-4">
                <div className="space-y-3">
                  <AnimatePresence>
                    {recentEntries.length > 0 ? (
                      recentEntries.map((entry, index) => (
                        <motion.div
                          key={entry.id}
                          initial={{ opacity: 0, x: -20 }}
                          animate={{ opacity: 1, x: 0 }}
                          exit={{ opacity: 0, x: 20 }}
                          transition={{ delay: index * 0.1 }}
                        >
                          <EntryCard entry={entry} index={index} />
                        </motion.div>
                      ))
                    ) : (
                      <EmptyState
                        icon={Mic}
                        title="No entries yet"
                        description="Send a voice note to your Telegram bot to get started!"
                      />
                    )}
                  </AnimatePresence>
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </motion.div>

        {/* Category Breakdown */}
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.5 }}
        >
          <Card className="premium-card h-full overflow-hidden">
            <CardHeader className="pb-3 border-b border-border/30">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-primary/10 border border-primary/20">
                  <BarChart3 className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <CardTitle className="text-lg">Categories</CardTitle>
                  <CardDescription className="text-xs">Distribution of entries</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-4">
              {stats?.categories && Object.keys(stats.categories).length > 0 ? (
                <div className="space-y-4">
                  {Object.entries(stats.categories)
                    .sort(([, a], [, b]) => b - a)
                    .slice(0, 6)
                    .map(([category, count], index) => {
                      const percentage = totalCategories > 0 
                        ? Math.round((count / totalCategories) * 100) 
                        : 0;
                      const Icon = categoryIcons[category.toLowerCase()] || Zap;
                      const gradient = categoryGradients[category.toLowerCase()] || 'from-gray-500 to-slate-500';
                      
                      return (
                        <motion.div 
                          key={category} 
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: 0.6 + index * 0.1 }}
                          className="space-y-2"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <div className={`p-1.5 rounded-lg bg-gradient-to-r ${gradient} text-white`}>
                                <Icon className="h-3.5 w-3.5" />
                              </div>
                              <span className="text-sm font-medium capitalize">
                                {category}
                              </span>
                            </div>
                            <span className="text-xs text-muted-foreground font-mono">
                              {count} ({percentage}%)
                            </span>
                          </div>
                          <div className="h-2 w-full rounded-full bg-muted/50 overflow-hidden">
                            <motion.div
                              initial={{ width: 0 }}
                              animate={{ width: `${percentage}%` }}
                              transition={{ delay: 0.8 + index * 0.1, duration: 0.5 }}
                              className={`h-full rounded-full bg-gradient-to-r ${gradient}`}
                            />
                          </div>
                        </motion.div>
                      );
                    })}
                </div>
              ) : (
                <EmptyState
                  icon={BarChart3}
                  title="No data yet"
                  description="Categories will appear as you log entries"
                />
              )}
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* Quick Actions */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.7 }}
      >
        <Card className="premium-card overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-r from-primary/5 via-transparent to-accent/5 pointer-events-none" />
          <CardHeader className="relative border-b border-border/30">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-primary/10 border border-primary/20">
                <Sparkles className="h-5 w-5 text-primary" />
              </div>
              <div>
                <CardTitle className="text-lg">Quick Actions</CardTitle>
                <CardDescription className="text-xs">Common tasks at your fingertips</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="relative pt-6">
            <div className="grid gap-4 md:grid-cols-3">
              {[
                {
                  icon: Mic,
                  title: "Log Entry",
                  description: "Send a voice note via Telegram",
                  gradient: "from-blue-500 to-cyan-500"
                },
                {
                  icon: FileText,
                  title: "Generate Post",
                  description: "Create your weekly LinkedIn post",
                  gradient: "from-purple-500 to-pink-500"
                },
                {
                  icon: Calendar,
                  title: "View Summary",
                  description: "Check your daily reflection",
                  gradient: "from-green-500 to-emerald-500"
                }
              ].map((action, index) => (
                <motion.div
                  key={action.title}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.8 + index * 0.1 }}
                >
                  <QuickActionCard {...action} />
                </motion.div>
              ))}
            </div>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
}

interface StatsCardProps {
  title: string;
  value: number | string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  trend?: number;
  trendLabel?: string;
  gradient: string;
  isStreak?: boolean;
}

function StatsCard({ title, value, description, icon: Icon, trend, trendLabel, gradient, isStreak }: StatsCardProps) {
  return (
    <Card className="premium-card relative overflow-hidden group">
      <div className={`absolute inset-0 bg-gradient-to-br ${gradient} opacity-0 group-hover:opacity-5 transition-opacity duration-500`} />
      <div className={`absolute top-0 left-0 right-0 h-1 bg-gradient-to-r ${gradient} opacity-60`} />
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2 relative">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <div className={`p-2.5 rounded-xl bg-gradient-to-br ${gradient} text-white shadow-lg`}>
          <Icon className="h-4 w-4" />
        </div>
      </CardHeader>
      <CardContent className="relative">
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-bold">{value}</span>
          {isStreak && typeof value === 'number' && value > 0 && (
            <motion.span 
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ type: 'spring', stiffness: 500, delay: 0.3 }}
              className="text-orange-500 text-xl"
            >
              
            </motion.span>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-1">{description}</p>
        {trend !== undefined && trend > 0 && (
          <motion.div 
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.5 }}
            className="mt-3 flex items-center text-xs text-primary font-medium"
          >
            <TrendingUp className="mr-1 h-3.5 w-3.5" />
            +{trend} {trendLabel}
          </motion.div>
        )}
      </CardContent>
    </Card>
  );
}

interface EntryCardProps {
  entry: Entry;
  index: number;
}

function EntryCard({ entry, index }: EntryCardProps) {
  const Icon = categoryIcons[entry.category?.toLowerCase()] || Zap;
  const gradient = categoryGradients[entry.category?.toLowerCase()] || 'from-gray-500 to-slate-500';

  return (
    <div 
      className="group p-4 rounded-xl bg-muted/30 hover:bg-muted/50 transition-all duration-300 border border-border/30 hover:border-border/50"
    >
      <div className="flex items-start gap-3">
        <div className={`p-2 rounded-xl bg-gradient-to-br ${gradient} text-white shrink-0 shadow-lg`}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <Badge variant="outline" className="capitalize text-xs rounded-lg border-border/50">
              {entry.category || 'entry'}
            </Badge>
            <span className="text-xs text-muted-foreground font-mono">
              {formatRelativeTime(entry.created_at)}
            </span>
          </div>
          <p className="mt-2 text-sm text-muted-foreground line-clamp-2">
            {entry.raw_text || 'No content'}
          </p>
        </div>
      </div>
    </div>
  );
}

interface QuickActionCardProps {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  gradient: string;
}

function QuickActionCard({ icon: Icon, title, description, gradient }: QuickActionCardProps) {
  return (
    <motion.div 
      whileHover={{ scale: 1.02, y: -2 }}
      whileTap={{ scale: 0.98 }}
      className="group p-5 rounded-2xl bg-muted/30 hover:bg-muted/50 border border-border/30 hover:border-primary/30 transition-all duration-300 cursor-pointer"
    >
      <motion.div 
        whileHover={{ scale: 1.1, rotate: 5 }}
        className={`inline-flex p-3 rounded-xl bg-gradient-to-br ${gradient} text-white mb-4 shadow-lg`}
      >
        <Icon className="h-5 w-5" />
      </motion.div>
      <h3 className="font-semibold">{title}</h3>
      <p className="text-sm text-muted-foreground mt-1">{description}</p>
    </motion.div>
  );
}

interface EmptyStateProps {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
}

function EmptyState({ icon: Icon, title, description }: EmptyStateProps) {
  return (
    <motion.div 
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      className="flex flex-col items-center justify-center py-12 text-center"
    >
      <motion.div 
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: 'spring', stiffness: 200 }}
        className="p-4 rounded-2xl bg-muted/50 mb-4"
      >
        <Icon className="h-8 w-8 text-muted-foreground" />
      </motion.div>
      <h3 className="font-medium text-muted-foreground">{title}</h3>
      <p className="text-sm text-muted-foreground/70 mt-1">{description}</p>
    </motion.div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-8">
      <div className="rounded-3xl bg-card p-8 border border-border/30">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-4 w-64 mt-2" />
      </div>
      
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <Card key={i} className="premium-card shimmer">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <Skeleton className="h-4 w-24 bg-muted/50" />
              <Skeleton className="h-10 w-10 rounded-xl bg-muted/50" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-8 w-16 bg-muted/50" />
              <Skeleton className="h-3 w-32 mt-2 bg-muted/50" />
            </CardContent>
          </Card>
        ))}
      </div>
      
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2 premium-card shimmer">
          <CardHeader>
            <Skeleton className="h-6 w-32 bg-muted/50" />
            <Skeleton className="h-4 w-48 bg-muted/50" />
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-20 w-full rounded-xl bg-muted/50" />
              ))}
            </div>
          </CardContent>
        </Card>
        
        <Card className="premium-card shimmer">
          <CardHeader>
            <Skeleton className="h-6 w-24 bg-muted/50" />
            <Skeleton className="h-4 w-40 bg-muted/50" />
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="space-y-2">
                  <div className="flex justify-between">
                    <Skeleton className="h-4 w-20 bg-muted/50" />
                    <Skeleton className="h-4 w-12 bg-muted/50" />
                  </div>
                  <Skeleton className="h-2 w-full rounded-full bg-muted/50" />
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
