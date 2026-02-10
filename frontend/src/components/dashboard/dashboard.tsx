'use client';

import { useEffect, useState } from 'react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Mic,
  FileText,
  Calendar,
  TrendingUp,
  Clock,
  Zap,
  Target,
  BookOpen,
  Code,
  Lightbulb,
  Trophy,
  AlertTriangle,
} from 'lucide-react';
import { fetchAPIWithUser, getTelegramId, formatDate, formatRelativeTime, getCategoryColor } from '@/lib/utils';

interface StatsData {
  total_entries: number;
  total_posts: number;
  total_summaries: number;
  entries_this_week: number;
  last_entry_date: string | null;
  categories: Record<string, number>;
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
};

export function Dashboard() {
  const [stats, setStats] = useState<StatsData | null>(null);
  const [recentEntries, setRecentEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        setLoading(true);
        
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
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load data');
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  if (loading) {
    return <DashboardSkeleton />;
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const statCards = [
    {
      title: 'Total Entries',
      value: stats?.total_entries || 0,
      description: 'Voice notes processed',
      icon: Mic,
      trend: stats?.entries_this_week || 0,
      trendLabel: 'this week',
    },
    {
      title: 'Weekly Posts',
      value: stats?.total_posts || 0,
      description: 'LinkedIn posts generated',
      icon: FileText,
    },
    {
      title: 'Daily Summaries',
      value: stats?.total_summaries || 0,
      description: 'Reflections created',
      icon: Calendar,
    },
    {
      title: 'Last Activity',
      value: stats?.last_entry_date
        ? formatRelativeTime(stats.last_entry_date)
        : 'No entries yet',
      description: stats?.last_entry_date
        ? formatDate(stats.last_entry_date)
        : 'Start by sending a voice note',
      icon: Clock,
      isText: true,
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Dashboard</h2>
        <p className="text-muted-foreground">
          Your weekly progress at a glance
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {statCards.map((stat) => (
          <Card key={stat.title}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                {stat.title}
              </CardTitle>
              <stat.icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div
                className={
                  stat.isText ? 'text-lg font-bold' : 'text-2xl font-bold'
                }
              >
                {stat.value}
              </div>
              <p className="text-xs text-muted-foreground">
                {stat.description}
              </p>
              {stat.trend !== undefined && (
                <div className="mt-2 flex items-center text-xs text-green-600">
                  <TrendingUp className="mr-1 h-3 w-3" />
                  {stat.trend} {stat.trendLabel}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Category Breakdown */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Zap className="h-5 w-5" />
              Category Breakdown
            </CardTitle>
            <CardDescription>
              Distribution of your entries by type
            </CardDescription>
          </CardHeader>
          <CardContent>
            {stats?.categories && Object.keys(stats.categories).length > 0 ? (
              <div className="space-y-3">
                {Object.entries(stats.categories).map(([category, count]) => {
                  const total = Object.values(stats.categories).reduce(
                    (a, b) => a + b,
                    0
                  );
                  const percentage = Math.round((count / total) * 100);
                  const IconComponent =
                    categoryIcons[category] || FileText;

                  return (
                    <div key={category} className="space-y-1">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <IconComponent className="h-4 w-4" />
                          <span className="text-sm font-medium capitalize">
                            {category}
                          </span>
                        </div>
                        <span className="text-sm text-muted-foreground">
                          {count} ({percentage}%)
                        </span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                        <div
                          className={`h-full ${getCategoryColor(category)}`}
                          style={{ width: `${percentage}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No entries yet. Send a voice note to get started!
              </p>
            )}
          </CardContent>
        </Card>

        {/* Recent Entries */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Mic className="h-5 w-5" />
              Recent Entries
            </CardTitle>
            <CardDescription>Your latest voice note transcriptions</CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[280px]">
              {recentEntries.length > 0 ? (
                <div className="space-y-4">
                  {recentEntries.map((entry) => (
                    <div
                      key={entry.id}
                      className="flex flex-col space-y-2 rounded-lg border p-3"
                    >
                      <div className="flex items-center justify-between">
                        <Badge
                          variant={entry.category as any}
                          className="capitalize"
                        >
                          {entry.category}
                        </Badge>
                        <span className="text-xs text-muted-foreground">
                          {formatRelativeTime(entry.created_at)}
                        </span>
                      </div>
                      <p className="line-clamp-2 text-sm">{entry.raw_text}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex h-full items-center justify-center">
                  <p className="text-sm text-muted-foreground">
                    No entries yet
                  </p>
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      {/* Quick Tips */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Lightbulb className="h-5 w-5" />
            Quick Tips
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-lg border p-4">
              <h4 className="font-medium">🎤 Voice Notes</h4>
              <p className="mt-1 text-sm text-muted-foreground">
                Send voice notes to your Telegram bot to log your daily progress
              </p>
            </div>
            <div className="rounded-lg border p-4">
              <h4 className="font-medium">📝 Weekly Posts</h4>
              <p className="mt-1 text-sm text-muted-foreground">
                Posts are automatically generated every Sunday at midnight
              </p>
            </div>
            <div className="rounded-lg border p-4">
              <h4 className="font-medium">🔄 Commands</h4>
              <p className="mt-1 text-sm text-muted-foreground">
                Use /summary for daily recap or /generate for on-demand posts
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <div>
        <Skeleton className="h-8 w-48" />
        <Skeleton className="mt-2 h-4 w-64" />
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <Card key={i}>
            <CardHeader className="pb-2">
              <Skeleton className="h-4 w-24" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-8 w-16" />
              <Skeleton className="mt-2 h-3 w-32" />
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <Skeleton className="h-5 w-40" />
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <Skeleton className="h-5 w-40" />
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {[...Array(3)].map((_, i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
