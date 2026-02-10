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
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  FileText,
  Copy,
  Check,
  Edit,
  Calendar,
  RefreshCw,
  Linkedin,
  Sparkles,
  ChevronLeft,
  ChevronRight,
  Plus,
} from 'lucide-react';
import { fetchAPI, fetchAPIWithUser, getTelegramId, formatDate, getToneColor } from '@/lib/utils';
import { useToast } from '@/components/ui/use-toast';
import { Input } from '@/components/ui/input';

interface Post {
  id: number;
  week_start: string;
  week_end: string;
  tone: string;
  content: string;
  entry_count: number;
  created_at: string;
}

interface PostsResponse {
  posts: Post[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

const tones = [
  { value: 'professional', label: 'Professional', emoji: '💼' },
  { value: 'casual', label: 'Casual', emoji: '😊' },
  { value: 'inspirational', label: 'Inspirational', emoji: '✨' },
];

export function PostsView() {
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [selectedPost, setSelectedPost] = useState<Post | null>(null);
  const [editedContent, setEditedContent] = useState('');
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [generateTone, setGenerateTone] = useState('professional');
  const [showGenerateDialog, setShowGenerateDialog] = useState(false);
  const [showManualEntryDialog, setShowManualEntryDialog] = useState(false);
  const [manualContent, setManualContent] = useState('');
  const [manualWeekNumber, setManualWeekNumber] = useState('');
  const [importing, setImporting] = useState(false);
  const { toast } = useToast();

  const fetchPosts = async () => {
    try {
      setLoading(true);
      
      const telegramId = getTelegramId();
      if (!telegramId) {
        setError('Please set your Telegram ID in Settings first');
        setLoading(false);
        return;
      }
      
      const data: PostsResponse = await fetchAPIWithUser(`/api/posts?page=${page}&limit=10`);
      setPosts(data.posts || []);
      setTotalPages(data.total_pages || 1);
      setTotal(data.total || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load posts');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPosts();
  }, [page]);

  const handleCopy = async (post: Post) => {
    try {
      await navigator.clipboard.writeText(post.content);
      setCopiedId(post.id);
      toast({
        title: 'Copied!',
        description: 'Post content copied to clipboard',
      });
      setTimeout(() => setCopiedId(null), 2000);
    } catch (err) {
      toast({
        title: 'Failed to copy',
        description: 'Could not copy to clipboard',
        variant: 'destructive',
      });
    }
  };

  const handleEdit = (post: Post) => {
    setSelectedPost(post);
    setEditedContent(post.content);
  };

  const handleSaveEdit = async () => {
    if (!selectedPost) return;
    try {
      await fetchAPI(`/api/posts/${selectedPost.id}`, {
        method: 'PUT',
        body: JSON.stringify({ content: editedContent }),
      });
      setPosts((prev) =>
        prev.map((p) =>
          p.id === selectedPost.id ? { ...p, content: editedContent } : p
        )
      );
      setSelectedPost(null);
      toast({
        title: 'Saved!',
        description: 'Post has been updated',
      });
    } catch (err) {
      toast({
        title: 'Failed to save',
        description: err instanceof Error ? err.message : 'Could not save post',
        variant: 'destructive',
      });
    }
  };

  const handleGenerate = async () => {
    try {
      setGenerating(true);
      setShowGenerateDialog(false);
      const result = await fetchAPIWithUser('/api/generate', {
        method: 'POST',
        body: JSON.stringify({ custom_instructions: `Use a ${generateTone} tone` }),
      });
      toast({
        title: 'Post generation started!',
        description: 'Check back in a moment for your new post',
      });
      setTimeout(() => fetchPosts(), 3000);
    } catch (err) {
      toast({
        title: 'Generation failed',
        description: err instanceof Error ? err.message : 'Could not generate post',
        variant: 'destructive',
      });
    } finally {
      setGenerating(false);
    }
  };

  const handleManualEntry = async () => {
    if (!manualContent.trim() || !manualWeekNumber) {
      toast({
        title: 'Missing information',
        description: 'Please enter both content and week number',
        variant: 'destructive',
      });
      return;
    }

    const weekNum = parseInt(manualWeekNumber, 10);
    if (isNaN(weekNum) || weekNum < 1) {
      toast({
        title: 'Invalid week number',
        description: 'Please enter a valid week number',
        variant: 'destructive',
      });
      return;
    }

    try {
      setImporting(true);
      await fetchAPIWithUser('/api/posts/import', {
        method: 'POST',
        body: JSON.stringify({
          content: manualContent,
          week_number: weekNum,
        }),
      });
      toast({
        title: 'Post imported!',
        description: `Week ${weekNum} progress report has been added`,
      });
      setShowManualEntryDialog(false);
      setManualContent('');
      setManualWeekNumber('');
      fetchPosts();
    } catch (err) {
      toast({
        title: 'Import failed',
        description: err instanceof Error ? err.message : 'Could not import post',
        variant: 'destructive',
      });
    } finally {
      setImporting(false);
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
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">LinkedIn Posts</h2>
          <p className="text-muted-foreground">
            Weekly generated posts ({total} total)
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setShowManualEntryDialog(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Manual Entry
          </Button>
          <Button onClick={() => setShowGenerateDialog(true)} disabled={generating}>
            {generating ? (
              <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="mr-2 h-4 w-4" />
            )}
            Generate Now
          </Button>
        </div>
      </div>

      {/* Posts Grid */}
      {loading ? (
        <div className="grid gap-6 md:grid-cols-2">
          {[...Array(4)].map((_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-6 w-48" />
                <Skeleton className="h-4 w-32" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-32 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : posts.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <FileText className="h-12 w-12 text-muted-foreground" />
            <h3 className="mt-4 text-lg font-medium">No posts yet</h3>
            <p className="mt-2 text-center text-sm text-muted-foreground">
              Posts are automatically generated every Sunday, or you can generate one now.
            </p>
            <Button
              className="mt-4"
              onClick={() => setShowGenerateDialog(true)}
              disabled={generating}
            >
              <Sparkles className="mr-2 h-4 w-4" />
              Generate Your First Post
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-6 md:grid-cols-2">
            {posts.map((post) => (
              <Card key={post.id} className="flex flex-col">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="flex items-center gap-2 text-lg">
                      <Linkedin className="h-5 w-5 text-[#0A66C2]" />
                      Week of {formatDate(post.week_start)}
                    </CardTitle>
                    <Badge
                      className={getToneColor(post.tone)}
                      variant="secondary"
                    >
                      {tones.find((t) => t.value === post.tone)?.emoji}{' '}
                      {post.tone}
                    </Badge>
                  </div>
                  <CardDescription className="flex items-center gap-2">
                    <Calendar className="h-3 w-3" />
                    {formatDate(post.week_start)} - {formatDate(post.week_end)}
                    <span className="text-muted-foreground">
                      • {post.entry_count} entries
                    </span>
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex-1">
                  <ScrollArea className="h-48">
                    <p className="whitespace-pre-wrap text-sm">{post.content}</p>
                  </ScrollArea>
                </CardContent>
                <div className="flex gap-2 border-t p-4">
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => handleCopy(post)}
                  >
                    {copiedId === post.id ? (
                      <Check className="mr-2 h-4 w-4 text-green-500" />
                    ) : (
                      <Copy className="mr-2 h-4 w-4" />
                    )}
                    Copy
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => handleEdit(post)}
                  >
                    <Edit className="mr-2 h-4 w-4" />
                    Edit
                  </Button>
                </div>
              </Card>
            ))}
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

      {/* Edit Dialog */}
      <Dialog open={!!selectedPost} onOpenChange={() => setSelectedPost(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit Post</DialogTitle>
            <DialogDescription>
              Week of {selectedPost && formatDate(selectedPost.week_start)}
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            className="min-h-[300px]"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setSelectedPost(null)}>
              Cancel
            </Button>
            <Button onClick={handleSaveEdit}>Save Changes</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Generate Dialog */}
      <Dialog open={showGenerateDialog} onOpenChange={setShowGenerateDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Generate LinkedIn Post</DialogTitle>
            <DialogDescription>
              Create a new post based on this week's entries
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Select Tone</label>
              <Tabs value={generateTone} onValueChange={setGenerateTone}>
                <TabsList className="grid w-full grid-cols-3">
                  {tones.map((tone) => (
                    <TabsTrigger key={tone.value} value={tone.value}>
                      {tone.emoji} {tone.label}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
            </div>
            <p className="text-sm text-muted-foreground">
              {generateTone === 'professional' &&
                'A polished, business-appropriate tone for professional networking.'}
              {generateTone === 'casual' &&
                'A friendly, conversational tone that feels approachable.'}
              {generateTone === 'inspirational' &&
                'An uplifting, motivational tone to inspire your audience.'}
            </p>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowGenerateDialog(false)}
            >
              Cancel
            </Button>
            <Button onClick={handleGenerate} disabled={generating}>
              {generating ? (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="mr-2 h-4 w-4" />
              )}
              Generate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Manual Entry Dialog */}
      <Dialog open={showManualEntryDialog} onOpenChange={setShowManualEntryDialog}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Historical Post</DialogTitle>
            <DialogDescription>
              Manually add a previously posted progress report
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Week Number</label>
              <Input
                type="number"
                placeholder="e.g., 57"
                value={manualWeekNumber}
                onChange={(e) => setManualWeekNumber(e.target.value)}
                min={1}
              />
              <p className="text-xs text-muted-foreground">
                The week number for this progress report
              </p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Post Content</label>
              <Textarea
                placeholder="Paste your LinkedIn post content here..."
                value={manualContent}
                onChange={(e) => setManualContent(e.target.value)}
                className="min-h-[250px]"
              />
              <p className="text-xs text-muted-foreground">
                Paste the full content of your previously posted progress report
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setShowManualEntryDialog(false);
                setManualContent('');
                setManualWeekNumber('');
              }}
            >
              Cancel
            </Button>
            <Button onClick={handleManualEntry} disabled={importing}>
              {importing ? (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Plus className="mr-2 h-4 w-4" />
              )}
              Add Post
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
