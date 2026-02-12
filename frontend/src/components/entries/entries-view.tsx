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
} from 'lucide-react';
import { fetchAPIWithUser, getTelegramId, formatDate, formatRelativeTime } from '@/lib/utils';

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
  { value: 'all', label: 'All Categories' },
  { value: 'coding', label: 'Coding' },
  { value: 'learning', label: 'Learning' },
  { value: 'project', label: 'Project' },
  { value: 'reflection', label: 'Reflection' },
  { value: 'challenge', label: 'Challenge' },
  { value: 'achievement', label: 'Achievement' },
];

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
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load entries');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEntries();
  }, [page, categoryFilter]);

  const handleSearch = () => {
    setPage(1);
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
      setEntryToDelete(null);
      fetchEntries();
    } catch (err) {
      console.error('Failed to delete entry:', err);
    } finally {
      setDeleting(false);
    }
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
        <h2 className="text-3xl font-bold tracking-tight">Voice Entries</h2>
        <p className="text-muted-foreground">
          All your transcribed voice notes ({total} total)
        </p>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col gap-4 sm:flex-row">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search entries..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                className="pl-9"
              />
            </div>
            <Select value={categoryFilter} onValueChange={setCategoryFilter}>
              <SelectTrigger className="w-full sm:w-48">
                <Filter className="mr-2 h-4 w-4" />
                <SelectValue placeholder="Category" />
              </SelectTrigger>
              <SelectContent>
                {categories.map((cat) => (
                  <SelectItem key={cat.value} value={cat.value}>
                    {cat.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button onClick={handleSearch}>Search</Button>
          </div>
        </CardContent>
      </Card>

      {/* Entries List */}
      <Card>
        <CardContent className="pt-6">
          {loading ? (
            <div className="space-y-4">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="flex gap-4 rounded-lg border p-4">
                  <Skeleton className="h-12 w-12 rounded-full" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-24" />
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-4 w-3/4" />
                  </div>
                </div>
              ))}
            </div>
          ) : entries.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <Mic className="h-12 w-12 text-muted-foreground" />
              <h3 className="mt-4 text-lg font-medium">No entries found</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                {searchQuery || categoryFilter !== 'all'
                  ? 'Try adjusting your filters'
                  : 'Send a voice note to your Telegram bot to get started'}
              </p>
            </div>
          ) : (
            <ScrollArea className="h-[500px]">
              <div className="space-y-4 pr-4">
                {entries.map((entry) => (
                  <div
                    key={entry.id}
                    className="flex gap-4 rounded-lg border p-4 transition-colors hover:bg-muted/50"
                  >
                    <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                      <Mic className="h-6 w-6 text-primary" />
                    </div>
                    <div className="flex-1 space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Badge
                            variant={entry.category as any}
                            className="capitalize"
                          >
                            {entry.category}
                          </Badge>
                          <span className="flex items-center gap-1 text-xs text-muted-foreground">
                            <Calendar className="h-3 w-3" />
                            {formatDate(entry.date)}
                          </span>
                        </div>
                        <div className="flex gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setSelectedEntry(entry)}
                          >
                            <Eye className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setEntryToDelete(entry)}
                            className="text-destructive hover:text-destructive"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>
                      <p className="line-clamp-2 text-sm">{entry.raw_text}</p>
                      {entry.structured_data?.keywords &&
                        entry.structured_data.keywords.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {entry.structured_data.keywords
                              .slice(0, 3)
                              .map((keyword, i) => (
                                <Badge
                                  key={i}
                                  variant="outline"
                                  className="text-xs"
                                >
                                  {keyword}
                                </Badge>
                              ))}
                          </div>
                        )}
                      <p className="text-xs text-muted-foreground">
                        {formatRelativeTime(entry.created_at)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-6 flex items-center justify-between">
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
        </CardContent>
      </Card>

      {/* Entry Detail Dialog */}
      <Dialog open={!!selectedEntry} onOpenChange={() => setSelectedEntry(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Badge
                variant={selectedEntry?.category as any}
                className="capitalize"
              >
                {selectedEntry?.category}
              </Badge>
              Entry Details
            </DialogTitle>
            <DialogDescription>
              {selectedEntry && formatDate(selectedEntry.date)}
            </DialogDescription>
          </DialogHeader>
          {selectedEntry && (
            <div className="space-y-4">
              <div>
                <h4 className="mb-2 font-medium">Transcription</h4>
                <p className="rounded-lg bg-muted p-4 text-sm">
                  {selectedEntry.raw_text}
                </p>
              </div>
              {selectedEntry.structured_data?.accomplishments &&
                selectedEntry.structured_data.accomplishments.length > 0 && (
                  <div>
                    <h4 className="mb-2 font-medium">Accomplishments</h4>
                    <ul className="list-inside list-disc space-y-1 text-sm">
                      {selectedEntry.structured_data.accomplishments.map(
                        (point, i) => (
                          <li key={i}>{point}</li>
                        )
                      )}
                    </ul>
                  </div>
                )}
              {selectedEntry.structured_data?.keywords &&
                selectedEntry.structured_data.keywords.length > 0 && (
                  <div>
                    <h4 className="mb-2 font-medium">Keywords</h4>
                    <div className="flex flex-wrap gap-2">
                      {selectedEntry.structured_data.keywords.map((keyword, i) => (
                        <Badge key={i} variant="outline">
                          {keyword}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              {selectedEntry.structured_data?.sentiment && (
                <div>
                  <h4 className="mb-2 font-medium">Sentiment</h4>
                  <Badge variant="secondary">
                    {selectedEntry.structured_data.sentiment}
                  </Badge>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <AlertDialog open={!!entryToDelete} onOpenChange={() => setEntryToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Entry</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this entry? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? 'Deleting...' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
