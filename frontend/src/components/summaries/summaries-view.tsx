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
  BarChart3,
  FileText,
  Sparkles,
  Clock,
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

// Animation variants
const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.08 },
  },
};

const cardVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { type: 'spring' as const, stiffness: 100, damping: 15 },
  },
};

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
    if (score >= 80) return 'text-green-500 bg-green-500/10 border-green-500/20';
    if (score >= 60) return 'text-amber-500 bg-amber-500/10 border-amber-500/20';
    return 'text-red-500 bg-red-500/10 border-red-500/20';
  };

  const getScoreIcon = (score: number) => {
    if (score >= 80) return TrendingUp;
    if (score >= 60) return Minus;
    return TrendingDown;
  };

  const avgScore = summaries.length > 0 
    ? Math.round(summaries.reduce((acc, s) => acc + s.productivity_score, 0) / summaries.length)
    : 0;

  if (error) {
    return (
      <motion.div 
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="flex h-full items-center justify-center"
      >
        <Card className="premium-card w-full max-w-md">
          <CardHeader className="text-center">
            <div className="mx-auto p-3 rounded-full bg-destructive/10 w-fit mb-4">
              <Target className="h-8 w-8 text-destructive" />
            </div>
            <CardTitle className="text-destructive">Configuration Required</CardTitle>
            <CardDescription className="text-base">{error}</CardDescription>
          </CardHeader>
        </Card>
      </motion.div>
    );
  }

  return (
    <div className="space-y-8 pb-8">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-card via-card to-muted/30 p-8 border border-border/30"
      >
        <div className="absolute -top-24 -right-24 w-48 h-48 bg-purple-500/10 rounded-full blur-3xl" />
        <div className="absolute -bottom-24 -left-24 w-48 h-48 bg-primary/10 rounded-full blur-3xl" />
        
        <div className="relative flex flex-col md:flex-row md:items-center md:justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <motion.div
                initial={{ scale: 0, rotate: -180 }}
                animate={{ scale: 1, rotate: 0 }}
                transition={{ type: 'spring', stiffness: 200, damping: 15 }}
                className="p-2.5 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 border border-purple-500/20"
              >
                <BarChart3 className="h-6 w-6 text-purple-500" />
              </motion.div>
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight">
                <span className="gradient-text">Daily Summaries</span>
              </h1>
            </div>
            <p className="text-muted-foreground max-w-md">
              Your daily reflections and AI-powered insights
            </p>
          </div>
          
          {!loading && summaries.length > 0 && (
            <motion.div 
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="flex items-center gap-4"
            >
              <div className="text-center px-4 py-2 rounded-xl bg-muted/30 border border-border/30">
                <p className="text-2xl font-bold text-foreground">{total}</p>
                <p className="text-xs text-muted-foreground">Total</p>
              </div>
              <div className="text-center px-4 py-2 rounded-xl bg-primary/5 border border-primary/20">
                <p className="text-2xl font-bold text-primary">{avgScore}%</p>
                <p className="text-xs text-muted-foreground">Avg Score</p>
              </div>
            </motion.div>
          )}
        </div>
      </motion.div>

      {/* Summaries List */}
      {loading ? (
        <motion.div 
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="space-y-4"
        >
          {[...Array(5)].map((_, i) => (
            <motion.div key={i} variants={cardVariants}>
              <Card className="premium-card">
                <CardHeader className="pb-3">
                  <Skeleton className="h-6 w-48 rounded-lg" />
                  <Skeleton className="h-4 w-32 rounded-lg" />
                </CardHeader>
                <CardContent>
                  <Skeleton className="h-20 w-full rounded-lg" />
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </motion.div>
      ) : summaries.length === 0 ? (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <Card className="premium-card">
            <CardContent className="flex flex-col items-center justify-center py-16">
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', stiffness: 200, damping: 15, delay: 0.2 }}
                className="p-4 rounded-full bg-muted/50 mb-4"
              >
                <Calendar className="h-12 w-12 text-muted-foreground" />
              </motion.div>
              <h3 className="text-xl font-semibold">No summaries yet</h3>
              <p className="mt-2 text-center text-sm text-muted-foreground max-w-sm">
                Daily summaries are automatically generated at midnight based on your entries.
              </p>
            </CardContent>
          </Card>
        </motion.div>
      ) : (
        <>
          <motion.div 
            variants={containerVariants}
            initial="hidden"
            animate="visible"
            className="space-y-4"
          >
            <AnimatePresence>
              {summaries.map((summary, index) => {
                const ScoreIcon = getScoreIcon(summary.productivity_score);
                return (
                  <motion.div
                    key={summary.id}
                    variants={cardVariants}
                    layout
                    whileHover={{ scale: 1.01 }}
                    transition={{ type: 'spring', stiffness: 300, damping: 20 }}
                  >
                    <Card
                      className="premium-card cursor-pointer group"
                      onClick={() => setSelectedSummary(summary)}
                    >
                      <CardHeader className="pb-3">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                          <CardTitle className="flex items-center gap-3 text-lg">
                            <div className="p-2 rounded-xl bg-purple-500/10 border border-purple-500/20">
                              <Calendar className="h-4 w-4 text-purple-500" />
                            </div>
                            <span className="font-semibold">{formatDate(summary.date)}</span>
                          </CardTitle>
                          <div className="flex items-center gap-3">
                            <Badge 
                              variant="outline" 
                              className="rounded-lg border-border/50 text-xs font-medium"
                            >
                              <FileText className="h-3 w-3 mr-1.5" />
                              {summary.entry_count} entries
                            </Badge>
                            <div
                              className={`flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm font-semibold border ${getScoreColor(summary.productivity_score)}`}
                            >
                              <ScoreIcon className="h-4 w-4" />
                              {summary.productivity_score}%
                            </div>
                          </div>
                        </div>
                        {summary.themes.length > 0 && (
                          <div className="flex flex-wrap gap-2 mt-2">
                            {summary.themes.slice(0, 4).map((theme, i) => (
                              <Badge 
                                key={i} 
                                variant="secondary"
                                className="rounded-lg text-xs"
                              >
                                {theme}
                              </Badge>
                            ))}
                            {summary.themes.length > 4 && (
                              <Badge variant="outline" className="rounded-lg text-xs">
                                +{summary.themes.length - 4} more
                              </Badge>
                            )}
                          </div>
                        )}
                      </CardHeader>
                      <CardContent>
                        <p className="line-clamp-3 text-sm text-muted-foreground leading-relaxed">
                          {summary.content}
                        </p>
                        <Button 
                          variant="ghost" 
                          size="sm" 
                          className="mt-4 rounded-xl group-hover:bg-muted/50 transition-all"
                        >
                          <Eye className="mr-2 h-4 w-4" />
                          View Details
                        </Button>
                      </CardContent>
                    </Card>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </motion.div>

          {/* Pagination */}
          {totalPages > 1 && (
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.4 }}
              className="flex items-center justify-between pt-4"
            >
              <p className="text-sm text-muted-foreground">
                Page <span className="font-medium text-foreground">{page}</span> of{' '}
                <span className="font-medium text-foreground">{totalPages}</span>
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="rounded-xl border-border/50 hover:border-primary/50"
                >
                  <ChevronLeft className="h-4 w-4 mr-1" />
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="rounded-xl border-border/50 hover:border-primary/50"
                >
                  Next
                  <ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              </div>
            </motion.div>
          )}
        </>
      )}

      {/* Summary Detail Dialog */}
      <Dialog
        open={!!selectedSummary}
        onOpenChange={() => setSelectedSummary(null)}
      >
        <DialogContent className="max-w-2xl rounded-2xl border-border/40 bg-card/95 backdrop-blur-sm">
          <DialogHeader className="border-b border-border/30 pb-4">
            <DialogTitle className="flex items-center gap-3 text-xl">
              <div className="p-2 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 border border-purple-500/20">
                <Calendar className="h-5 w-5 text-purple-500" />
              </div>
              Daily Summary
            </DialogTitle>
            <DialogDescription className="flex flex-wrap items-center gap-3 pt-2">
              <Badge className="rounded-lg bg-muted text-muted-foreground border-0">
                <Clock className="h-3 w-3 mr-1.5" />
                {selectedSummary && formatDate(selectedSummary.date)}
              </Badge>
              <Badge variant="outline" className="rounded-lg">
                <FileText className="h-3 w-3 mr-1.5" />
                {selectedSummary?.entry_count} entries
              </Badge>
              {selectedSummary && (
                <div
                  className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-semibold border ${getScoreColor(selectedSummary.productivity_score)}`}
                >
                  <TrendingUp className="h-3 w-3" />
                  {selectedSummary.productivity_score}% productivity
                </div>
              )}
            </DialogDescription>
          </DialogHeader>
          {selectedSummary && (
            <ScrollArea className="max-h-[60vh]">
              <div className="space-y-6 pr-4 py-2">
                {/* Themes */}
                {selectedSummary.themes.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.1 }}
                  >
                    <h4 className="mb-3 flex items-center gap-2 font-semibold">
                      <Target className="h-4 w-4 text-primary" />
                      Themes
                    </h4>
                    <div className="flex flex-wrap gap-2">
                      {selectedSummary.themes.map((theme, i) => (
                        <Badge 
                          key={i} 
                          variant="secondary"
                          className="rounded-lg"
                        >
                          {theme}
                        </Badge>
                      ))}
                    </div>
                  </motion.div>
                )}

                {/* Reflection */}
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 }}
                >
                  <h4 className="mb-3 flex items-center gap-2 font-semibold">
                    <Lightbulb className="h-4 w-4 text-amber-500" />
                    Reflection
                  </h4>
                  <div className="whitespace-pre-wrap rounded-xl bg-muted/50 border border-border/30 p-4 text-sm leading-relaxed">
                    {selectedSummary.content}
                  </div>
                </motion.div>

                {/* Highlights */}
                {selectedSummary.highlights.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.3 }}
                  >
                    <h4 className="mb-3 flex items-center gap-2 font-semibold">
                      <Star className="h-4 w-4 text-yellow-500" />
                      Highlights
                    </h4>
                    <ul className="space-y-2 text-sm">
                      {selectedSummary.highlights.map((highlight, i) => (
                        <li key={i} className="flex items-start gap-2">
                          <Sparkles className="h-4 w-4 text-yellow-500 mt-0.5 shrink-0" />
                          <span>{highlight}</span>
                        </li>
                      ))}
                    </ul>
                  </motion.div>
                )}

                {/* Areas for Improvement */}
                {selectedSummary.areas_for_improvement.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.4 }}
                  >
                    <h4 className="mb-3 flex items-center gap-2 font-semibold">
                      <TrendingUp className="h-4 w-4 text-blue-500" />
                      Areas for Improvement
                    </h4>
                    <ul className="space-y-2 text-sm">
                      {selectedSummary.areas_for_improvement.map((area, i) => (
                        <li key={i} className="flex items-start gap-2">
                          <div className="h-4 w-4 rounded-full bg-blue-500/10 flex items-center justify-center mt-0.5 shrink-0">
                            <div className="h-1.5 w-1.5 rounded-full bg-blue-500" />
                          </div>
                          <span>{area}</span>
                        </li>
                      ))}
                    </ul>
                  </motion.div>
                )}
              </div>
            </ScrollArea>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
