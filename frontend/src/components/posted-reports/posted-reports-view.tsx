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
import { Input } from '@/components/ui/input';
import {
  FileText,
  Copy,
  Check,
  Calendar,
  Linkedin,
  Plus,
  ExternalLink,
  Maximize2,
  RefreshCw,
  CheckCircle2,
  Sparkles,
  TrendingUp,
  Award,
} from 'lucide-react';
import { fetchAPIWithUser, getTelegramId, formatDate } from '@/lib/utils';
import { useToast } from '@/components/ui/use-toast';

interface PostedReport {
  id: number;
  week_number: number;
  content: string;
  published_at: string;
  linkedin_url?: string;
  created_at: string;
}

interface PostedReportsResponse {
  reports: PostedReport[];
  total: number;
}

const REPORTS_PER_PAGE = 20;

// Animation variants
const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.08,
    },
  },
};

const cardVariants = {
  hidden: { opacity: 0, y: 20, scale: 0.95 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: {
      type: 'spring' as const,
      stiffness: 100,
      damping: 15,
    },
  },
};

export function PostedReportsView() {
  const [reports, setReports] = useState<PostedReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [showManualEntryDialog, setShowManualEntryDialog] = useState(false);
  const [selectedReport, setSelectedReport] = useState<PostedReport | null>(null);
  const [manualContent, setManualContent] = useState('');
  const [manualWeekNumber, setManualWeekNumber] = useState('');
  const [linkedinUrl, setLinkedinUrl] = useState('');
  const [importing, setImporting] = useState(false);
  const [totalReports, setTotalReports] = useState(0);
  const [offset, setOffset] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const { toast } = useToast();

  const hasMore = reports.length < totalReports;

  const fetchReports = async (loadMore = false) => {
    try {
      if (loadMore) {
        setLoadingMore(true);
      } else {
        setLoading(true);
        setOffset(0);
      }
      
      const telegramId = getTelegramId();
      if (!telegramId) {
        setError('Please set your Telegram ID in Settings first');
        setLoading(false);
        return;
      }
      
      const currentOffset = loadMore ? offset : 0;
      const data: PostedReportsResponse = await fetchAPIWithUser(
        `/api/posted-reports?limit=${REPORTS_PER_PAGE}&offset=${currentOffset}`
      );
      
      if (loadMore) {
        setReports(prev => [...prev, ...(data.reports || [])]);
      } else {
        setReports(data.reports || []);
      }
      setTotalReports(data.total || 0);
      setOffset(currentOffset + REPORTS_PER_PAGE);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch reports');
    } finally {
      setLoading(false);
      setLoadingMore(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchReports();
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchReports();
  };

  const handleCopy = async (report: PostedReport, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    try {
      await navigator.clipboard.writeText(report.content);
      setCopiedId(report.id);
      toast({
        title: 'Copied!',
        description: 'Report content copied to clipboard',
      });
      setTimeout(() => setCopiedId(null), 2000);
    } catch (err) {
      toast({
        title: 'Copy failed',
        description: 'Could not copy to clipboard',
        variant: 'destructive',
      });
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
          linkedin_url: linkedinUrl || undefined,
        }),
      });
      toast({
        title: 'Report Added!',
        description: `Week ${weekNum} posted report has been saved`,
      });
      setShowManualEntryDialog(false);
      setManualContent('');
      setManualWeekNumber('');
      setLinkedinUrl('');
      fetchReports();
    } catch (err) {
      toast({
        title: 'Import failed',
        description: err instanceof Error ? err.message : 'Could not add report',
        variant: 'destructive',
      });
    } finally {
      setImporting(false);
    }
  };

  if (error) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex h-full items-center justify-center p-6"
      >
        <Card className="w-full max-w-md premium-card">
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      </motion.div>
    );
  }

  return (
    <div className="space-y-8 pb-8">
      {/* Hero Header */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-card via-card to-muted/30 p-8 border border-border/30"
      >
        {/* Decorative elements */}
        <div className="absolute -top-24 -right-24 w-48 h-48 bg-primary/10 rounded-full blur-3xl" />
        <div className="absolute -bottom-24 -left-24 w-48 h-48 bg-accent/10 rounded-full blur-3xl" />
        
        <div className="relative flex flex-col md:flex-row md:items-center md:justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-primary/10 border border-primary/20">
                <Award className="h-6 w-6 text-primary" />
              </div>
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight">
                <span className="gradient-text">Posted Reports</span>
              </h1>
            </div>
            <p className="text-muted-foreground max-w-md">
              Your published LinkedIn progress reports — {totalReports} weeks of documented growth
            </p>
          </div>
          
          <div className="flex items-center gap-3">
            <Button 
              variant="outline" 
              size="icon" 
              onClick={handleRefresh} 
              disabled={refreshing}
              className="btn-magnetic rounded-xl border-border/50 hover:border-primary/50 hover:bg-primary/5"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
            </Button>
            <Button 
              onClick={() => setShowManualEntryDialog(true)} 
              className="btn-magnetic rounded-xl bg-gradient-to-r from-primary to-primary/80 hover:from-primary/90 hover:to-primary/70 shadow-lg shadow-primary/25"
            >
              <Plus className="mr-2 h-4 w-4" />
              Add Report
            </Button>
          </div>
        </div>

        {/* Stats row */}
        {totalReports > 0 && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            className="relative mt-8 pt-6 border-t border-border/30 grid grid-cols-3 gap-4"
          >
            <div className="text-center">
              <p className="text-2xl font-bold text-foreground">{totalReports}</p>
              <p className="text-xs text-muted-foreground font-medium">Total Posts</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-primary">{reports[0]?.week_number || 0}</p>
              <p className="text-xs text-muted-foreground font-medium">Latest Week</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-foreground">{Math.round(totalReports / 4)}</p>
              <p className="text-xs text-muted-foreground font-medium">Months Active</p>
            </div>
          </motion.div>
        )}
      </motion.div>

      {/* Reports Grid */}
      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <Card key={i} className="premium-card shimmer">
              <CardHeader>
                <Skeleton className="h-6 w-24 bg-muted/50" />
                <Skeleton className="h-4 w-32 bg-muted/50 mt-2" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-24 w-full bg-muted/50" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : reports.length === 0 ? (
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
                className="p-6 rounded-2xl bg-gradient-to-br from-primary/10 to-primary/5 mb-6"
              >
                <Sparkles className="h-12 w-12 text-primary" />
              </motion.div>
              <h3 className="text-xl font-semibold mb-2">Start Your Journey</h3>
              <p className="text-muted-foreground text-center mb-8 max-w-md">
                Add your published LinkedIn posts to track your progress and help generate better future content.
              </p>
              <Button 
                onClick={() => setShowManualEntryDialog(true)} 
                className="btn-magnetic rounded-xl bg-gradient-to-r from-primary to-primary/80 shadow-lg shadow-primary/25"
              >
                <Plus className="mr-2 h-4 w-4" />
                Add Your First Report
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
            className="grid gap-4 md:grid-cols-2 lg:grid-cols-3"
          >
            {reports.map((report, index) => (
              <motion.div key={report.id} variants={cardVariants}>
                <Card 
                  className="premium-card flex flex-col cursor-pointer group relative overflow-hidden h-full"
                  onClick={() => setSelectedReport(report)}
                >
                  {/* Accent gradient line */}
                  <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-primary via-primary/80 to-accent opacity-80" />
                  
                  {/* Hover glow */}
                  <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
                  
                  <CardHeader className="pb-3 relative">
                    <div className="flex items-center justify-between">
                      <motion.div
                        whileHover={{ scale: 1.05 }}
                        className="week-badge"
                      >
                        Week {report.week_number}
                      </motion.div>
                      <Maximize2 className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-all duration-300 transform group-hover:translate-x-0 translate-x-2" />
                    </div>
                    <CardDescription className="flex items-center gap-1.5 mt-3 text-xs">
                      <Calendar className="h-3.5 w-3.5" />
                      <span className="font-mono">{formatDate(report.published_at)}</span>
                    </CardDescription>
                  </CardHeader>
                  
                  <CardContent className="flex-1 relative">
                    <p className="text-sm leading-relaxed line-clamp-4 text-muted-foreground">
                      {report.content.substring(0, 180)}...
                    </p>
                  </CardContent>
                  
                  <div className="px-6 pb-4 pt-2 border-t border-border/30 flex items-center gap-2">
                    {report.linkedin_url && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-xs rounded-lg hover:bg-muted/50"
                        onClick={(e) => {
                          e.stopPropagation();
                          window.open(report.linkedin_url, '_blank');
                        }}
                      >
                        <ExternalLink className="h-3 w-3 mr-1.5" />
                        View
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-xs rounded-lg hover:bg-muted/50"
                      onClick={(e) => handleCopy(report, e)}
                    >
                      {copiedId === report.id ? (
                        <>
                          <Check className="h-3 w-3 mr-1.5 text-primary" />
                          <span className="text-primary">Copied</span>
                        </>
                      ) : (
                        <>
                          <Copy className="h-3 w-3 mr-1.5" />
                          Copy
                        </>
                      )}
                    </Button>
                  </div>
                </Card>
              </motion.div>
            ))}
          </motion.div>
          
          {/* Load More Button */}
          {hasMore && (
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex justify-center pt-6"
            >
              <Button
                variant="outline"
                onClick={() => fetchReports(true)}
                disabled={loadingMore}
                className="btn-magnetic rounded-xl border-border/50 hover:border-primary/50 hover:bg-primary/5"
              >
                {loadingMore ? (
                  <span className="flex items-center gap-2">
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    Loading...
                  </span>
                ) : (
                  <>Load More ({totalReports - reports.length} remaining)</>
                )}
              </Button>
            </motion.div>
          )}
        </>
      )}

      {/* View Report Dialog */}
      <Dialog open={!!selectedReport} onOpenChange={() => setSelectedReport(null)}>
        <DialogContent className="max-w-3xl max-h-[90vh] flex flex-col rounded-2xl border-border/50">
          <DialogHeader className="pb-4 border-b border-border/30">
            <div className="flex items-center gap-3">
              <div className="week-badge">
                Week {selectedReport?.week_number}
              </div>
              <span className="text-muted-foreground text-sm font-mono">
                {selectedReport && formatDate(selectedReport.published_at)}
              </span>
            </div>
          </DialogHeader>
          
          <ScrollArea className="flex-1 max-h-[60vh] pr-4 py-4">
            <div className="whitespace-pre-wrap text-sm leading-relaxed">
              {selectedReport?.content}
            </div>
          </ScrollArea>
          
          <DialogFooter className="pt-4 border-t border-border/30 flex-row gap-2 sm:justify-end">
            {selectedReport?.linkedin_url && (
              <Button variant="outline" asChild className="rounded-xl">
                <a href={selectedReport.linkedin_url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="mr-2 h-4 w-4" />
                  View on LinkedIn
                </a>
              </Button>
            )}
            <Button
              variant="outline"
              className="rounded-xl"
              onClick={() => selectedReport && handleCopy(selectedReport)}
            >
              {copiedId === selectedReport?.id ? (
                <>
                  <Check className="mr-2 h-4 w-4 text-primary" />
                  Copied!
                </>
              ) : (
                <>
                  <Copy className="mr-2 h-4 w-4" />
                  Copy Content
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Manual Entry Dialog */}
      <Dialog open={showManualEntryDialog} onOpenChange={setShowManualEntryDialog}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border-border/50">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-[#0A66C2]/10">
                <Linkedin className="h-5 w-5 text-[#0A66C2]" />
              </div>
              Add Posted Report
            </DialogTitle>
            <DialogDescription>
              Add an existing LinkedIn post that you have already published to track your progress.
            </DialogDescription>
          </DialogHeader>
          
          <div className="space-y-5 py-6">
            <div className="space-y-2">
              <label className="text-sm font-medium">Week Number</label>
              <Input
                type="number"
                placeholder="e.g., 42"
                value={manualWeekNumber}
                onChange={(e) => setManualWeekNumber(e.target.value)}
                min={1}
                className="rounded-xl"
              />
            </div>
            
            <div className="space-y-2">
              <label className="text-sm font-medium">LinkedIn URL <span className="text-muted-foreground">(Optional)</span></label>
              <Input
                type="url"
                placeholder="https://www.linkedin.com/posts/..."
                value={linkedinUrl}
                onChange={(e) => setLinkedinUrl(e.target.value)}
                className="rounded-xl"
              />
            </div>
            
            <div className="space-y-2">
              <label className="text-sm font-medium">Post Content</label>
              <Textarea
                placeholder="Paste your LinkedIn post content here..."
                value={manualContent}
                onChange={(e) => setManualContent(e.target.value)}
                rows={12}
                className="resize-none font-mono text-sm rounded-xl"
              />
              <p className="text-xs text-muted-foreground font-mono">
                {manualContent.length} characters
              </p>
            </div>
          </div>
          
          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={() => setShowManualEntryDialog(false)}
              className="rounded-xl"
            >
              Cancel
            </Button>
            <Button 
              onClick={handleManualEntry} 
              disabled={importing} 
              className="btn-magnetic rounded-xl bg-gradient-to-r from-primary to-primary/80"
            >
              {importing ? 'Adding...' : 'Add Report'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

