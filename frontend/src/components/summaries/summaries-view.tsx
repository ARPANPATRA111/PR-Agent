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
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Calendar,
  ChevronLeft,
  ChevronRight,
  Eye,
  TrendingUp,
  TrendingDown,
  Minus,
  Lightbulb,
  Target,
  Star,
} from 'lucide-react';
import { fetchAPIWithUser, getTelegramId, formatDate } from '@/lib/utils';

interface Summary {
  id: number;
  date: string;
  content: string;
  entry_count: number;
  productivity_score: number;
  themes: string[];
  highlights: string[];
  areas_for_improvement: string[];
  created_at: string;
}

interface SummariesResponse {
  summaries: Summary[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export function SummariesView() {
  const [summaries, setSummaries] = useState<Summary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [selectedSummary, setSelectedSummary] = useState<Summary | null>(null);

  const fetchSummaries = async () => {
    try {
      setLoading(true);
      
      const telegramId = getTelegramId();
      if (!telegramId) {
        setError('Please set your Telegram ID in Settings first');
        setLoading(false);
        return;
      }
      
      const data: SummariesResponse = await fetchAPIWithUser(
        `/api/summaries?page=${page}&limit=10`
      );
      setSummaries(data.summaries || []);
      setTotalPages(data.total_pages || 1);
      setTotal(data.total || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load summaries');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSummaries();
  }, [page]);

  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-green-600 bg-green-100';
    if (score >= 60) return 'text-yellow-600 bg-yellow-100';
    return 'text-red-600 bg-red-100';
  };

  const getScoreIcon = (score: number) => {
    if (score >= 80) return TrendingUp;
    if (score >= 60) return Minus;
    return TrendingDown;
  };

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

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Daily Summaries</h2>
        <p className="text-muted-foreground">
          Your daily reflections and insights ({total} total)
        </p>
      </div>

      {/* Summaries List */}
      {loading ? (
        <div className="space-y-4">
          {[...Array(5)].map((_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-6 w-48" />
                <Skeleton className="h-4 w-32" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-20 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : summaries.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Calendar className="h-12 w-12 text-muted-foreground" />
            <h3 className="mt-4 text-lg font-medium">No summaries yet</h3>
            <p className="mt-2 text-center text-sm text-muted-foreground">
              Daily summaries are automatically generated at midnight based on your
              entries.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="space-y-4">
            {summaries.map((summary) => {
              const ScoreIcon = getScoreIcon(summary.productivity_score);
              return (
                <Card
                  key={summary.id}
                  className="cursor-pointer transition-colors hover:bg-muted/50"
                  onClick={() => setSelectedSummary(summary)}
                >
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <CardTitle className="flex items-center gap-2 text-lg">
                        <Calendar className="h-5 w-5" />
                        {formatDate(summary.date)}
                      </CardTitle>
                      <div className="flex items-center gap-3">
                        <Badge variant="outline">
                          {summary.entry_count} entries
                        </Badge>
                        <div
                          className={`flex items-center gap-1 rounded-full px-3 py-1 text-sm font-medium ${getScoreColor(summary.productivity_score)}`}
                        >
                          <ScoreIcon className="h-4 w-4" />
                          {summary.productivity_score}%
                        </div>
                      </div>
                    </div>
                    {summary.themes.length > 0 && (
                      <div className="flex flex-wrap gap-2">
                        {summary.themes.slice(0, 4).map((theme, i) => (
                          <Badge key={i} variant="secondary">
                            {theme}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </CardHeader>
                  <CardContent>
                    <p className="line-clamp-3 text-sm text-muted-foreground">
                      {summary.content}
                    </p>
                    <Button variant="ghost" size="sm" className="mt-3">
                      <Eye className="mr-2 h-4 w-4" />
                      View Details
                    </Button>
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                Page {page} of {totalPages}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                >
                  <ChevronLeft className="h-4 w-4" />
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                >
                  Next
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Summary Detail Dialog */}
      <Dialog
        open={!!selectedSummary}
        onOpenChange={() => setSelectedSummary(null)}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Calendar className="h-5 w-5" />
              Daily Summary - {selectedSummary && formatDate(selectedSummary.date)}
            </DialogTitle>
            <DialogDescription className="flex items-center gap-4">
              <Badge variant="outline">
                {selectedSummary?.entry_count} entries
              </Badge>
              {selectedSummary && (
                <div
                  className={`flex items-center gap-1 rounded-full px-3 py-1 text-sm font-medium ${getScoreColor(selectedSummary.productivity_score)}`}
                >
                  Productivity: {selectedSummary.productivity_score}%
                </div>
              )}
            </DialogDescription>
          </DialogHeader>
          {selectedSummary && (
            <ScrollArea className="max-h-[60vh]">
              <div className="space-y-6 pr-4">
                {/* Themes */}
                {selectedSummary.themes.length > 0 && (
                  <div>
                    <h4 className="mb-2 flex items-center gap-2 font-medium">
                      <Target className="h-4 w-4" />
                      Themes
                    </h4>
                    <div className="flex flex-wrap gap-2">
                      {selectedSummary.themes.map((theme, i) => (
                        <Badge key={i} variant="secondary">
                          {theme}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {/* Reflection */}
                <div>
                  <h4 className="mb-2 flex items-center gap-2 font-medium">
                    <Lightbulb className="h-4 w-4" />
                    Reflection
                  </h4>
                  <p className="whitespace-pre-wrap rounded-lg bg-muted p-4 text-sm">
                    {selectedSummary.content}
                  </p>
                </div>

                {/* Highlights */}
                {selectedSummary.highlights.length > 0 && (
                  <div>
                    <h4 className="mb-2 flex items-center gap-2 font-medium">
                      <Star className="h-4 w-4 text-yellow-500" />
                      Highlights
                    </h4>
                    <ul className="list-inside list-disc space-y-1 text-sm">
                      {selectedSummary.highlights.map((highlight, i) => (
                        <li key={i}>{highlight}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Areas for Improvement */}
                {selectedSummary.areas_for_improvement.length > 0 && (
                  <div>
                    <h4 className="mb-2 flex items-center gap-2 font-medium">
                      <TrendingUp className="h-4 w-4 text-blue-500" />
                      Areas for Improvement
                    </h4>
                    <ul className="list-inside list-disc space-y-1 text-sm">
                      {selectedSummary.areas_for_improvement.map((area, i) => (
                        <li key={i}>{area}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </ScrollArea>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
