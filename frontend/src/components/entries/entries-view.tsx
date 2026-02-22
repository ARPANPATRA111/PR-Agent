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
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Mic,
  Search,
  Filter,
  Calendar,
  ChevronLeft,
  ChevronRight,
  Eye,
  Trash2,
  RefreshCw,
  Hash,
  CheckCircle2,
  AlertTriangle,
  Sparkles,
  Code,
  BookOpen,
  Target,
  Lightbulb,
  Trophy,
  Brain,
  MessageSquare,
  Zap,
  AudioLines,
} from 'lucide-react';
import { fetchAPIWithUser, getTelegramId, formatDate, formatRelativeTime } from '@/lib/utils';
import { useToast } from '@/components/ui/use-toast';

interface Entry {
  id: number;
  date: string;
  category: string;
  raw_text: string;
  structured_data: {
    summary?: string;
    activities?: string[];
    blockers?: string[];
    accomplishments?: string[];
    learnings?: string[];
    keywords?: string[];
    sentiment?: string;
  };
  created_at: string;
}

interface EntriesResponse {
  entries: Entry[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

const categories = [
  { value: 'all', label: 'All Categories', icon: Sparkles },
  { value: 'coding', label: 'Coding', icon: Code },
  { value: 'learning', label: 'Learning', icon: BookOpen },
  { value: 'project', label: 'Project', icon: Target },
  { value: 'reflection', label: 'Reflection', icon: Lightbulb },
  { value: 'challenge', label: 'Challenge', icon: AlertTriangle },
  { value: 'achievement', label: 'Achievement', icon: Trophy },
  { value: 'research', label: 'Research', icon: Brain },
  { value: 'meeting', label: 'Meeting', icon: MessageSquare },
];

const categoryIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  coding: Code,
  learning: BookOpen,
  project: Target,
  reflection: Lightbulb,
  challenge: AlertTriangle,
  achievement: Trophy,
  research: Brain,
  meeting: MessageSquare,
  other: Zap,
};

const categoryGradients: Record<string, string> = {
  coding: 'from-blue-500 to-cyan-500',
  learning: 'from-purple-500 to-pink-500',
  project: 'from-green-500 to-emerald-500',
  reflection: 'from-amber-500 to-yellow-500',
  challenge: 'from-red-500 to-rose-500',
  achievement: 'from-orange-500 to-amber-500',
  research: 'from-indigo-500 to-violet-500',
  meeting: 'from-teal-500 to-cyan-500',
  other: 'from-gray-500 to-slate-500',
};

const sentimentConfig: Record<string, { color: string; icon: React.ComponentType<{ className?: string }> }> = {
  positive: { color: 'text-green-500', icon: CheckCircle2 },
  negative: { color: 'text-red-500', icon: AlertTriangle },
  neutral: { color: 'text-gray-500', icon: Zap },
};

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.06 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 15 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { type: 'spring' as const, stiffness: 120, damping: 20 },
  },
};

export function EntriesView() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [selectedEntry, setSelectedEntry] = useState<Entry | null>(null);
  const [entryToDelete, setEntryToDelete] = useState<Entry | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const { toast } = useToast();

  const fetchEntries = async () => {
    try {
      setLoading(true);
      
      const telegramId = getTelegramId();
      if (!telegramId) {
        setError('Please set your Telegram ID in Settings first');
        setLoading(false);
        return;
      }
      
      let url = `/api/entries?page=${page}&limit=10`;
      if (categoryFilter && categoryFilter !== 'all') {
        url += `&category=${categoryFilter}`;
      }
      if (searchQuery) {
        url += `&search=${encodeURIComponent(searchQuery)}`;
      }
      const data: EntriesResponse = await fetchAPIWithUser(url);
      setEntries(data.entries || []);
      setTotalPages(data.total_pages || 1);
      setTotal(data.total || 0);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load entries');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchEntries();
  }, [page, categoryFilter]);

  const handleSearch = () => {
    setPage(1);
    fetchEntries();
  };

  const handleRefresh = () => {
    setRefreshing(true);
    fetchEntries();
  };

  const handleDelete = async () => {
    if (!entryToDelete) return;
    
    const telegramId = getTelegramId();
    if (!telegramId) return;
    
    try {
      setDeleting(true);
      await fetchAPIWithUser(`/api/entries/${entryToDelete.id}`, {
        method: 'DELETE',
      });
      toast({
        title: 'Entry Deleted',
        description: 'The entry has been permanently removed.',
      });
      setEntryToDelete(null);
      fetchEntries();
    } catch (err) {
      toast({
        title: 'Delete Failed',
        description: 'Could not delete the entry. Please try again.',
        variant: 'destructive',
      });
    } finally {
      setDeleting(false);
    }
  };

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

  return (
    <div className="space-y-8 pb-8">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-card via-card to-muted/30 p-8 border border-border/30"
      >
        <div className="absolute -top-24 -right-24 w-48 h-48 bg-blue-500/10 rounded-full blur-3xl" />
        <div className="absolute -bottom-24 -left-24 w-48 h-48 bg-primary/10 rounded-full blur-3xl" />
        
        <div className="relative flex flex-col md:flex-row md:items-center md:justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', stiffness: 200, damping: 15 }}
                className="p-2.5 rounded-xl bg-gradient-to-br from-blue-500/20 to-blue-500/5 border border-blue-500/20"
              >
                <AudioLines className="h-6 w-6 text-blue-500" />
              </motion.div>
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight">
                <span className="gradient-text">Voice Entries</span>
              </h1>
            </div>
            <p className="text-muted-foreground max-w-md">
              {total > 0 ? `${total} transcribed notes captured` : 'Your transcribed voice notes'}
            </p>
          </div>
          
          <Button 
            onClick={handleRefresh} 
            variant="outline" 
            size="icon"
            disabled={refreshing}
            className="btn-magnetic rounded-xl border-border/50 hover:border-primary/50"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </motion.div>

      {/* Filters */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        <Card className="premium-card">
          <CardContent className="pt-6">
            <div className="flex flex-col gap-4 sm:flex-row">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Search entries..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                  className="pl-9 rounded-xl bg-muted/30 border-border/50 focus:border-primary/50"
                />
              </div>
              <Select value={categoryFilter} onValueChange={(v) => { setCategoryFilter(v); setPage(1); }}>
                <SelectTrigger className="w-full sm:w-56 rounded-xl bg-muted/30 border-border/50">
                  <Filter className="mr-2 h-4 w-4" />
                  <SelectValue placeholder="Category" />
                </SelectTrigger>
                <SelectContent>
                  {categories.map((cat) => {
                    const IconComponent = cat.icon;
                    return (
                      <SelectItem key={cat.value} value={cat.value}>
                        <div className="flex items-center gap-2">
                          <IconComponent className="h-4 w-4" />
                          {cat.label}
                        </div>
                      </SelectItem>
                    );
                  })}
                </SelectContent>
              </Select>
              <Button 
                onClick={handleSearch} 
                className="btn-magnetic rounded-xl bg-gradient-to-r from-primary to-primary/80 shadow-lg shadow-primary/25"
              >
                <Search className="mr-2 h-4 w-4" />
                Search
              </Button>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* Entries List */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <Card className="premium-card">
          <CardContent className="pt-6">
            {loading ? (
              <div className="space-y-4">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="flex gap-4 rounded-xl bg-muted/30 p-4 shimmer">
                    <Skeleton className="h-12 w-12 rounded-xl bg-muted/50" />
                    <div className="flex-1 space-y-2">
                      <Skeleton className="h-4 w-24 bg-muted/50" />
                      <Skeleton className="h-4 w-full bg-muted/50" />
                      <Skeleton className="h-4 w-3/4 bg-muted/50" />
                    </div>
                  </div>
                ))}
              </div>
            ) : entries.length === 0 ? (
              <motion.div 
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex flex-col items-center justify-center py-16"
              >
                <motion.div 
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 200 }}
                  className="p-6 rounded-2xl bg-gradient-to-br from-primary/10 to-primary/5 mb-6"
                >
                  <Mic className="h-12 w-12 text-primary" />
                </motion.div>
                <h3 className="text-xl font-semibold mb-2">No entries found</h3>
                <p className="text-muted-foreground text-center max-w-sm">
                  {searchQuery || categoryFilter !== 'all'
                    ? 'Try adjusting your filters or search terms'
                    : 'Send a voice note to your Telegram bot to get started'}
                </p>
              </motion.div>
            ) : (
              <ScrollArea className="h-[550px]">
                <motion.div 
                  variants={containerVariants}
                  initial="hidden"
                  animate="visible"
                  className="space-y-3 pr-4"
                >
                  <AnimatePresence>
                    {entries.map((entry, index) => {
                      const Icon = categoryIcons[entry.category?.toLowerCase()] || Mic;
                      const gradient = categoryGradients[entry.category?.toLowerCase()] || 'from-gray-500 to-slate-500';
                      
                      return (
                        <motion.div
                          key={entry.id}
                          variants={itemVariants}
                          layout
                          className="group flex gap-4 rounded-xl bg-muted/30 p-4 transition-all duration-300 hover:bg-muted/50 border border-border/30 hover:border-border/50"
                        >
                          <motion.div 
                            whileHover={{ scale: 1.05 }}
                            className={`flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br ${gradient} text-white shrink-0 shadow-lg`}
                          >
                            <Icon className="h-5 w-5" />
                          </motion.div>
                          <div className="flex-1 min-w-0 space-y-2">
                            <div className="flex items-center justify-between gap-2">
                              <div className="flex items-center gap-2 flex-wrap">
                                <Badge
                                  variant="outline"
                                  className="capitalize text-xs rounded-lg border-border/50"
                                >
                                  {entry.category || 'entry'}
                                </Badge>
                                <span className="flex items-center gap-1 text-xs text-muted-foreground font-mono">
                                  <Calendar className="h-3 w-3" />
                                  {formatDate(entry.date)}
                                </span>
                                {entry.structured_data?.sentiment && (
                                  <SentimentBadge sentiment={entry.structured_data.sentiment} />
                                )}
                              </div>
                              <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => setSelectedEntry(entry)}
                                  className="h-8 w-8 p-0 rounded-lg hover:bg-muted"
                                >
                                  <Eye className="h-4 w-4" />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => setEntryToDelete(entry)}
                                  className="h-8 w-8 p-0 rounded-lg text-destructive hover:text-destructive hover:bg-destructive/10"
                                >
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </div>
                            </div>
                            <p className="line-clamp-2 text-sm text-muted-foreground">{entry.raw_text}</p>
                            {entry.structured_data?.keywords &&
                              entry.structured_data.keywords.length > 0 && (
                                <div className="flex flex-wrap gap-1.5">
                                  {entry.structured_data.keywords
                                    .slice(0, 4)
                                    .map((keyword, i) => (
                                      <Badge
                                        key={i}
                                        variant="secondary"
                                        className="text-xs gap-1 rounded-lg bg-muted/50"
                                      >
                                        <Hash className="h-2.5 w-2.5" />
                                        {keyword}
                                      </Badge>
                                    ))}
                                  {entry.structured_data.keywords.length > 4 && (
                                    <Badge variant="secondary" className="text-xs rounded-lg bg-muted/50">
                                      +{entry.structured_data.keywords.length - 4}
                                    </Badge>
                                  )}
                                </div>
                              )}
                            <p className="text-xs text-muted-foreground/70 font-mono">
                              {formatRelativeTime(entry.created_at)}
                            </p>
                          </div>
                        </motion.div>
                      );
                    })}
                  </AnimatePresence>
                </motion.div>
              </ScrollArea>
            )}

            {/* Pagination */}
            {totalPages > 1 && (
              <motion.div 
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.4 }}
                className="mt-6 flex items-center justify-between border-t border-border/30 pt-4"
              >
                <p className="text-sm text-muted-foreground font-mono">
                  Page {page} of {totalPages}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="gap-1 rounded-lg border-border/50"
                  >
                    <ChevronLeft className="h-4 w-4" />
                    Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    className="gap-1 rounded-lg border-border/50"
                  >
                    Next
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </motion.div>
            )}
          </CardContent>
        </Card>
      </motion.div>

      {/* Entry Detail Dialog */}
      <Dialog open={!!selectedEntry} onOpenChange={() => setSelectedEntry(null)}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl border-border/50">
          <DialogHeader className="pb-4 border-b border-border/30">
            <DialogTitle className="flex items-center gap-3">
              <EntryIcon category={selectedEntry?.category} />
              Entry Details
            </DialogTitle>
            <DialogDescription className="flex items-center gap-3 mt-2">
              <span className="flex items-center gap-1.5 font-mono text-xs">
                <Calendar className="h-3.5 w-3.5" />
                {selectedEntry && formatDate(selectedEntry.date)}
              </span>
              {selectedEntry?.structured_data?.sentiment && (
                <SentimentBadge sentiment={selectedEntry.structured_data.sentiment} />
              )}
            </DialogDescription>
          </DialogHeader>
          {selectedEntry && (
            <div className="space-y-6 py-4">
              <div>
                <h4 className="text-sm font-medium text-muted-foreground mb-3 flex items-center gap-2">
                  <Mic className="h-4 w-4" />
                  Transcription
                </h4>
                <div className="rounded-xl bg-muted/30 p-4 border border-border/30">
                  <p className="text-sm leading-relaxed">{selectedEntry.raw_text}</p>
                </div>
              </div>
              
              {selectedEntry.structured_data?.accomplishments &&
                selectedEntry.structured_data.accomplishments.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-muted-foreground mb-3 flex items-center gap-2">
                      <CheckCircle2 className="h-4 w-4 text-green-500" />
                      Accomplishments
                    </h4>
                    <ul className="space-y-2">
                      {selectedEntry.structured_data.accomplishments.map((point, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm">
                          <span className="text-green-500 mt-1"></span>
                          {point}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              
              {selectedEntry.structured_data?.blockers &&
                selectedEntry.structured_data.blockers.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-muted-foreground mb-3 flex items-center gap-2">
                      <AlertTriangle className="h-4 w-4 text-amber-500" />
                      Blockers
                    </h4>
                    <ul className="space-y-2">
                      {selectedEntry.structured_data.blockers.map((point, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm">
                          <span className="text-amber-500 mt-1"></span>
                          {point}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              
              {selectedEntry.structured_data?.learnings &&
                selectedEntry.structured_data.learnings.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-muted-foreground mb-3 flex items-center gap-2">
                      <Lightbulb className="h-4 w-4 text-blue-500" />
                      Learnings
                    </h4>
                    <ul className="space-y-2">
                      {selectedEntry.structured_data.learnings.map((point, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm">
                          <span className="text-blue-500 mt-1"></span>
                          {point}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              
              {selectedEntry.structured_data?.keywords &&
                selectedEntry.structured_data.keywords.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-muted-foreground mb-3 flex items-center gap-2">
                      <Hash className="h-4 w-4" />
                      Keywords
                    </h4>
                    <div className="flex flex-wrap gap-2">
                      {selectedEntry.structured_data.keywords.map((keyword, i) => (
                        <Badge key={i} variant="secondary" className="gap-1 rounded-lg">
                          <Hash className="h-3 w-3" />
                          {keyword}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <AlertDialog open={!!entryToDelete} onOpenChange={() => setEntryToDelete(null)}>
        <AlertDialogContent className="rounded-2xl border-border/50">
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-destructive/10">
                <Trash2 className="h-5 w-5 text-destructive" />
              </div>
              Delete Entry
            </AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this entry? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="gap-2">
            <AlertDialogCancel disabled={deleting} className="rounded-xl">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={deleting}
              className="rounded-xl bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? (
                <>
                  <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                  Deleting...
                </>
              ) : (
                <>
                  <Trash2 className="mr-2 h-4 w-4" />
                  Delete
                </>
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function SentimentBadge({ sentiment }: { sentiment: string }) {
  const config = sentimentConfig[sentiment.toLowerCase()] || sentimentConfig.neutral;
  const Icon = config.icon;
  
  return (
    <Badge variant="outline" className={`gap-1 capitalize text-xs rounded-lg ${config.color}`}>
      <Icon className="h-3 w-3" />
      {sentiment}
    </Badge>
  );
}

function EntryIcon({ category }: { category?: string }) {
  const Icon = categoryIcons[category?.toLowerCase() || ''] || Mic;
  const gradient = categoryGradients[category?.toLowerCase() || ''] || 'from-gray-500 to-slate-500';
  
  return (
    <div className={`p-2 rounded-xl bg-gradient-to-br ${gradient} text-white shadow-lg`}>
      <Icon className="h-4 w-4" />
    </div>
  );
}
