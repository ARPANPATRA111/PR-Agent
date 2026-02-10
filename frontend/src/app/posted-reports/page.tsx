'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
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
  ArrowLeft,
  ExternalLink,
  Maximize2,
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

export default function PostedReportsPage() {
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
  const { toast } = useToast();
  const router = useRouter();

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
    }
  };

  useEffect(() => {
    fetchReports();
  }, []);

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
      <div className="flex h-full items-center justify-center p-6">
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
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.back()}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div>
            <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
              <FileText className="h-8 w-8 text-green-500" />
              Posted Reports
            </h1>
            <p className="text-muted-foreground">
              Your actually posted LinkedIn progress reports ({reports.length} total)
            </p>
          </div>
        </div>
        
        <Button onClick={() => setShowManualEntryDialog(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Add Posted Report
        </Button>
      </div>

      {/* Reports Grid */}
      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-6 w-24" />
                <Skeleton className="h-4 w-32" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-24 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : reports.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No Posted Reports Yet</CardTitle>
            <CardDescription>
              Add your first posted report using the button above
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {reports.map((report) => (
              <Card 
                key={report.id} 
                className="flex flex-col cursor-pointer hover:shadow-md transition-shadow"
                onClick={() => setSelectedReport(report)}
              >
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <Badge variant="secondary" className="bg-green-500/10 text-green-500">
                      Week {report.week_number}
                    </Badge>
                    <Maximize2 className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <CardDescription className="flex items-center gap-1 mt-2">
                    <Calendar className="h-3.5 w-3.5" />
                    {formatDate(report.published_at)}
                  </CardDescription>
                </CardHeader>
                
                <CardContent className="flex-1">
                  <div className="text-sm leading-relaxed line-clamp-4 text-muted-foreground">
                    {report.content.substring(0, 150)}...
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
          
          {/* Load More Button */}
          {hasMore && (
            <div className="flex justify-center pt-4">
              <Button
                variant="outline"
                onClick={() => fetchReports(true)}
                disabled={loadingMore}
                className="w-full sm:w-auto"
              >
                {loadingMore ? (
                  <>Loading...</>
                ) : (
                  <>Load More ({totalReports - reports.length} remaining)</>
                )}
              </Button>
            </div>
          )}
        </>
      )}

      {/* View Report Dialog - Mobile Responsive */}
      <Dialog open={!!selectedReport} onOpenChange={() => setSelectedReport(null)}>
        <DialogContent className="w-[95vw] max-w-3xl h-[90vh] sm:h-auto sm:max-h-[90vh] flex flex-col p-4 sm:p-6">
          <DialogHeader className="flex-shrink-0">
            <DialogTitle className="flex flex-col sm:flex-row sm:items-center gap-2">
              <Badge variant="secondary" className="bg-green-500/10 text-green-500 w-fit">
                Week {selectedReport?.week_number}
              </Badge>
              <span className="text-muted-foreground text-sm font-normal">
                {selectedReport && formatDate(selectedReport.published_at)}
              </span>
            </DialogTitle>
          </DialogHeader>
          
          <ScrollArea className="flex-1 min-h-0 pr-4 my-4">
            <div className="whitespace-pre-wrap text-sm leading-relaxed">
              {selectedReport?.content}
            </div>
          </ScrollArea>
          
          <DialogFooter className="flex-shrink-0 flex-col sm:flex-row gap-2">
            {selectedReport?.linkedin_url && (
              <Button variant="outline" className="w-full sm:w-auto" asChild>
                <a href={selectedReport.linkedin_url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="mr-2 h-4 w-4" />
                  View on LinkedIn
                </a>
              </Button>
            )}
            <Button
              variant="outline"
              className="w-full sm:w-auto"
              onClick={() => selectedReport && handleCopy(selectedReport)}
            >
              {copiedId === selectedReport?.id ? (
                <>
                  <Check className="mr-2 h-4 w-4 text-green-500" />
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
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Linkedin className="h-5 w-5 text-blue-500" />
              Add Posted Report
            </DialogTitle>
            <DialogDescription>
              Add an existing LinkedIn post that you have already published.
              This will be used as context for future post generation.
            </DialogDescription>
          </DialogHeader>
          
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Week Number</label>
              <Input
                type="number"
                placeholder="e.g., 42"
                value={manualWeekNumber}
                onChange={(e) => setManualWeekNumber(e.target.value)}
                min={1}
              />
            </div>
            
            <div className="space-y-2">
              <label className="text-sm font-medium">LinkedIn URL (Optional)</label>
              <Input
                type="url"
                placeholder="https://www.linkedin.com/posts/..."
                value={linkedinUrl}
                onChange={(e) => setLinkedinUrl(e.target.value)}
              />
            </div>
            
            <div className="space-y-2">
              <label className="text-sm font-medium">Post Content</label>
              <Textarea
                placeholder="Paste your LinkedIn post content here..."
                value={manualContent}
                onChange={(e) => setManualContent(e.target.value)}
                rows={12}
                className="resize-none font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                {manualContent.length} characters
              </p>
            </div>
          </div>
          
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowManualEntryDialog(false)}
            >
              Cancel
            </Button>
            <Button onClick={handleManualEntry} disabled={importing}>
              {importing ? 'Adding...' : 'Add Report'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
