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
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import { ScrollArea } from '@/components/ui/scroll-area';
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
  ExternalLink,
  Eye,
  AlertTriangle,
  Hash,
  TrendingUp,
  Wand2,
  Trash2,
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
  { value: 'professional', label: 'Professional', emoji: '', description: 'Polished, business-appropriate tone' },
  { value: 'casual', label: 'Casual', emoji: '', description: 'Friendly, conversational tone' },
  { value: 'inspirational', label: 'Inspirational', emoji: '', description: 'Uplifting, motivational tone' },
];

const toneGradients: Record<string, string> = {
  professional: 'from-blue-500 to-indigo-500',
  casual: 'from-green-500 to-teal-500',
  inspirational: 'from-purple-500 to-pink-500',
};

// Animation variants
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

export function PostsView() {
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [selectedPost, setSelectedPost] = useState<Post | null>(null);
  const [previewPost, setPreviewPost] = useState<Post | null>(null);
  const [editedContent, setEditedContent] = useState('');
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [generateTone, setGenerateTone] = useState('professional');
  const [showGenerateDialog, setShowGenerateDialog] = useState(false);
  const [showManualEntryDialog, setShowManualEntryDialog] = useState(false);
  const [manualContent, setManualContent] = useState('');
  const [manualWeekNumber, setManualWeekNumber] = useState('');
  const [importing, setImporting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
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
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load posts');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchPosts();
  }, [page]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchPosts();
  };

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

  const handleDelete = async (post: Post) => {
    if (!confirm('Are you sure you want to delete this post?')) return;
    try {
      await fetchAPIWithUser(`/api/posts/${post.id}`, {
        method: 'DELETE',
      });
      setPosts((prev) => prev.filter((p) => p.id !== post.id));
      setTotal((prev) => prev - 1);
      toast({
        title: 'Deleted!',
        description: 'Post has been removed',
      });
    } catch (err) {
      toast({
        title: 'Failed to delete',
        description: err instanceof Error ? err.message : 'Could not delete post',
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

  const getLinkedInShareUrl = (content: string) => {
    const encodedContent = encodeURIComponent(content);
    return `https://www.linkedin.com/feed/?shareActive=true&text=${encodedContent}`;
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
        <div className="absolute -top-24 -right-24 w-48 h-48 bg-[#0A66C2]/15 rounded-full blur-3xl" />
        <div className="absolute -bottom-24 -left-24 w-48 h-48 bg-primary/10 rounded-full blur-3xl" />
        
        <div className="relative flex flex-col md:flex-row md:items-center md:justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', stiffness: 200, damping: 15 }}
                className="p-2.5 rounded-xl bg-[#0A66C2]/10 border border-[#0A66C2]/20"
              >
                <Linkedin className="h-6 w-6 text-[#0A66C2]" />
              </motion.div>
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight">
                <span className="bg-gradient-to-r from-[#0A66C2] to-[#0A66C2]/60 bg-clip-text text-transparent">LinkedIn Posts</span>
              </h1>
            </div>
            <p className="text-muted-foreground max-w-md">
              {total > 0 ? `${total} weekly progress reports generated` : 'Your AI-generated weekly posts'}
            </p>
          </div>
          
          <div className="flex gap-3 flex-wrap">
            <Button 
              variant="outline" 
              size="icon" 
              onClick={handleRefresh}
              disabled={refreshing}
              className="btn-magnetic rounded-xl border-border/50 hover:border-primary/50"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
            </Button>
            <Button 
              variant="outline" 
              onClick={() => setShowManualEntryDialog(true)}
              className="btn-magnetic rounded-xl border-border/50 hover:border-primary/50"
            >
              <Plus className="mr-2 h-4 w-4" />
              Import
            </Button>
            <Button 
              onClick={() => setShowGenerateDialog(true)} 
              disabled={generating}
              className="btn-magnetic rounded-xl bg-gradient-to-r from-[#0A66C2] to-[#0A66C2]/80 hover:from-[#0A66C2]/90 hover:to-[#0A66C2]/70 shadow-lg shadow-[#0A66C2]/25"
            >
              {generating ? (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Wand2 className="mr-2 h-4 w-4" />
              )}
              Generate
            </Button>
          </div>
        </div>
      </motion.div>

      {/* Posts Grid */}
      {loading ? (
        <div className="grid gap-6 md:grid-cols-2">
          {[...Array(4)].map((_, i) => (
            <Card key={i} className="premium-card shimmer">
              <CardHeader>
                <Skeleton className="h-6 w-48 bg-muted/50" />
                <Skeleton className="h-4 w-32 bg-muted/50" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-32 w-full rounded-xl bg-muted/50" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : posts.length === 0 ? (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
        >
          <Card className="premium-card">
            <CardContent className="flex flex-col items-center justify-center py-20">
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', stiffness: 200, damping: 15 }}
                className="p-6 rounded-2xl bg-gradient-to-br from-[#0A66C2]/10 to-[#0A66C2]/5 mb-6"
              >
                <Linkedin className="h-12 w-12 text-[#0A66C2]" />
              </motion.div>
              <h3 className="text-xl font-semibold mb-2">No posts yet</h3>
              <p className="text-muted-foreground text-center max-w-md mb-8">
                Posts are automatically generated every Sunday, or you can generate one right now.
              </p>
              <Button
                className="btn-magnetic rounded-xl bg-gradient-to-r from-[#0A66C2] to-[#0A66C2]/80 shadow-lg shadow-[#0A66C2]/25"
                onClick={() => setShowGenerateDialog(true)}
                disabled={generating}
              >
                <Sparkles className="mr-2 h-4 w-4" />
                Generate Your First Post
              </Button>
            </CardContent>
          </Card>
        </motion.div>
      ) : (
        <>
          <motion.div 
            variants={containerVariants}
            initial="hidden"
            animate="visible"
            className="grid gap-6 md:grid-cols-2"
          >
            {posts.map((post) => {
              const toneGradient = toneGradients[post.tone] || toneGradients.professional;
              const toneInfo = tones.find(t => t.value === post.tone);
              
              return (
                <motion.div key={post.id} variants={cardVariants}>
                  <Card className="premium-card group relative overflow-hidden h-full">
                    <div className={`absolute top-0 left-0 right-0 h-1 bg-gradient-to-r ${toneGradient}`} />
                    
                    <div className="absolute inset-0 bg-gradient-to-br from-[#0A66C2]/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
                    
                    <CardHeader className="pb-3 relative">
                      <div className="flex items-center justify-between">
                        <CardTitle className="flex items-center gap-2 text-lg">
                          <div className="p-1.5 rounded-lg bg-[#0A66C2]/10">
                            <Linkedin className="h-4 w-4 text-[#0A66C2]" />
                          </div>
                          Week of {formatDate(post.week_start)}
                        </CardTitle>
                        <Badge className={`bg-gradient-to-r ${toneGradient} text-white border-0 rounded-lg`}>
                          {toneInfo?.emoji} {post.tone}
                        </Badge>
                      </div>
                      <CardDescription className="flex items-center gap-3 text-xs mt-2">
                        <span className="flex items-center gap-1 font-mono">
                          <Calendar className="h-3 w-3" />
                          {formatDate(post.week_start)} - {formatDate(post.week_end)}
                        </span>
                        <span className="flex items-center gap-1">
                          <Hash className="h-3 w-3" />
                          {post.entry_count} entries
                        </span>
                      </CardDescription>
                    </CardHeader>
                    
                    <CardContent className="pb-3 relative">
                      <div className="relative">
                        <ScrollArea className="h-36 rounded-xl bg-muted/30 p-4 border border-border/30">
                          <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{post.content}</p>
                        </ScrollArea>
                        <div className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-card to-transparent pointer-events-none rounded-b-xl" />
                      </div>
                    </CardContent>
                    
                    <div className="flex gap-2 border-t border-border/30 p-4">
                      <Button
                        variant="outline"
                        size="sm"
                        className="flex-1 gap-2 rounded-lg border-border/50 hover:border-primary/50"
                        onClick={() => setPreviewPost(post)}
                      >
                        <Eye className="h-4 w-4" />
                        Preview
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="flex-1 gap-2 rounded-lg border-border/50 hover:border-primary/50"
                        onClick={() => handleCopy(post)}
                      >
                        {copiedId === post.id ? (
                          <Check className="h-4 w-4 text-primary" />
                        ) : (
                          <Copy className="h-4 w-4" />
                        )}
                        Copy
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="flex-1 gap-2 rounded-lg border-border/50 hover:border-primary/50"
                        onClick={() => handleEdit(post)}
                      >
                        <Edit className="h-4 w-4" />
                        Edit
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-2 rounded-lg border-border/50 hover:border-destructive/50 hover:text-destructive"
                        onClick={() => handleDelete(post)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </Card>
                </motion.div>
              );
            })}
          </motion.div>

          {/* Pagination */}
          {totalPages > 1 && (
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.4 }}
              className="flex items-center justify-between border-t border-border/30 pt-4"
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
        </>
      )}

      <Dialog open={!!previewPost} onOpenChange={() => setPreviewPost(null)}>
        <DialogContent className="max-w-2xl max-h-[85vh] rounded-2xl border-border/50">
          <DialogHeader className="pb-4 border-b border-border/30">
            <DialogTitle className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-[#0A66C2]/10">
                <Linkedin className="h-5 w-5 text-[#0A66C2]" />
              </div>
              LinkedIn Post Preview
            </DialogTitle>
            <DialogDescription className="font-mono text-xs">
              Week of {previewPost && formatDate(previewPost.week_start)}
            </DialogDescription>
          </DialogHeader>
          {previewPost && (
            <div className="space-y-4 py-4">
              <div className="rounded-xl border border-border/50 bg-muted/30 p-4">
                <div className="flex items-center gap-3 mb-4">
                  <div className="h-12 w-12 rounded-full bg-gradient-to-br from-primary to-primary/60 flex items-center justify-center text-white font-bold text-lg">
                    U
                  </div>
                  <div>
                    <p className="font-semibold">Your Name</p>
                    <p className="text-xs text-muted-foreground">Your Title  1st</p>
                    <p className="text-xs text-muted-foreground">Just now  </p>
                  </div>
                </div>
                <ScrollArea className="max-h-[300px]">
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">{previewPost.content}</p>
                </ScrollArea>
              </div>
              
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  className="flex-1 rounded-xl"
                  onClick={() => handleCopy(previewPost)}
                >
                  {copiedId === previewPost.id ? (
                    <Check className="mr-2 h-4 w-4 text-primary" />
                  ) : (
                    <Copy className="mr-2 h-4 w-4" />
                  )}
                  Copy to Clipboard
                </Button>
                <Button
                  className="flex-1 rounded-xl bg-[#0A66C2] hover:bg-[#0A66C2]/90"
                  onClick={() => window.open(getLinkedInShareUrl(previewPost.content), '_blank')}
                >
                  <ExternalLink className="mr-2 h-4 w-4" />
                  Share on LinkedIn
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={!!selectedPost} onOpenChange={() => setSelectedPost(null)}>
        <DialogContent className="max-w-2xl rounded-2xl border-border/50">
          <DialogHeader className="pb-4 border-b border-border/30">
            <DialogTitle className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-primary/10">
                <Edit className="h-5 w-5 text-primary" />
              </div>
              Edit Post
            </DialogTitle>
            <DialogDescription className="font-mono text-xs">
              Week of {selectedPost && formatDate(selectedPost.week_start)}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-4">
            <label className="text-sm font-medium text-muted-foreground">Content</label>
            <Textarea
              value={editedContent}
              onChange={(e) => setEditedContent(e.target.value)}
              className="min-h-[300px] font-mono text-sm rounded-xl"
              placeholder="Edit your post content..."
            />
            <p className="text-xs text-muted-foreground text-right font-mono">
              {editedContent.length} characters
            </p>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setSelectedPost(null)} className="rounded-xl">
              Cancel
            </Button>
            <Button onClick={handleSaveEdit} className="rounded-xl">
              <Check className="mr-2 h-4 w-4" />
              Save Changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Generate Dialog */}
      <Dialog open={showGenerateDialog} onOpenChange={setShowGenerateDialog}>
        <DialogContent className="rounded-2xl border-border/50">
          <DialogHeader className="pb-4 border-b border-border/30">
            <DialogTitle className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-primary/10">
                <Wand2 className="h-5 w-5 text-primary" />
              </div>
              Generate LinkedIn Post
            </DialogTitle>
            <DialogDescription>
              Create a new post based on your recent entries
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-6">
            <div className="space-y-3">
              <label className="text-sm font-medium">Select Tone</label>
              <div className="grid grid-cols-3 gap-3">
                {tones.map((tone) => {
                  const isSelected = generateTone === tone.value;
                  return (
                    <motion.button
                      key={tone.value}
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      onClick={() => setGenerateTone(tone.value)}
                      className={`p-4 rounded-xl border-2 transition-all ${
                        isSelected 
                          ? 'border-primary bg-primary/5' 
                          : 'border-border/50 hover:border-primary/30'
                      }`}
                    >
                      <div className="text-2xl mb-2">{tone.emoji}</div>
                      <div className="text-sm font-medium">{tone.label}</div>
                    </motion.button>
                  );
                })}
              </div>
              <p className="text-sm text-muted-foreground text-center pt-2">
                {tones.find(t => t.value === generateTone)?.description}
              </p>
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setShowGenerateDialog(false)} className="rounded-xl">
              Cancel
            </Button>
            <Button 
              onClick={handleGenerate} 
              disabled={generating}
              className="rounded-xl bg-gradient-to-r from-primary to-primary/80"
            >
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
        <DialogContent className="max-w-2xl rounded-2xl border-border/50">
          <DialogHeader className="pb-4 border-b border-border/30">
            <DialogTitle className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-primary/10">
                <Plus className="h-5 w-5 text-primary" />
              </div>
              Import Historical Post
            </DialogTitle>
            <DialogDescription>
              Add a previously posted progress report to your collection
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-5 py-6">
            <div className="space-y-2">
              <label className="text-sm font-medium">Week Number</label>
              <Input
                type="number"
                placeholder="e.g., 57"
                value={manualWeekNumber}
                onChange={(e) => setManualWeekNumber(e.target.value)}
                min={1}
                className="rounded-xl"
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
                className="min-h-[250px] font-mono text-sm rounded-xl"
              />
              <p className="text-xs text-muted-foreground font-mono">
                {manualContent.length} characters
              </p>
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setShowManualEntryDialog(false);
                setManualContent('');
                setManualWeekNumber('');
              }}
              className="rounded-xl"
            >
              Cancel
            </Button>
            <Button 
              onClick={handleManualEntry} 
              disabled={importing}
              className="rounded-xl bg-gradient-to-r from-primary to-primary/80"
            >
              {importing ? (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Plus className="mr-2 h-4 w-4" />
              )}
              Import Post
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
