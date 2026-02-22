'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
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
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Settings as SettingsIcon,
  Bot,
  Clock,
  Linkedin,
  Bell,
  Database,
  Save,
  RefreshCw,
  Check,
  AlertCircle,
  Sparkles,
  Calendar,
  Zap,
  Server,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Cog,
} from 'lucide-react';
import { fetchAPI, getTelegramId, setTelegramId } from '@/lib/utils';
import { useToast } from '@/components/ui/use-toast';

interface SettingsData {
  telegram_id: string;
  default_tone: string;
  nudge_enabled: boolean;
  nudge_time: string;
  daily_reflection_time: string;
  weekly_summary_day: string;
  weekly_summary_time: string;
}

interface SystemStatus {
  status: string;
  scheduler_running: boolean;
  database_connected: boolean;
  vector_store_connected: boolean;
  telegram_connected: boolean;
  uptime: string;
}

const tones = [
  { value: 'professional', label: 'Professional', emoji: '', description: 'Polished and business-appropriate' },
  { value: 'casual', label: 'Casual', emoji: '', description: 'Friendly and conversational' },
  { value: 'inspirational', label: 'Inspirational', emoji: '', description: 'Uplifting and motivational' },
];

const weekdays = [
  { value: '0', label: 'Sunday' },
  { value: '1', label: 'Monday' },
  { value: '2', label: 'Tuesday' },
  { value: '3', label: 'Wednesday' },
  { value: '4', label: 'Thursday' },
  { value: '5', label: 'Friday' },
  { value: '6', label: 'Saturday' },
];

// Animation variants
const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.1 },
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

export function SettingsView() {
  const [settings, setSettings] = useState<SettingsData>({
    telegram_id: '',
    default_tone: 'professional',
    nudge_enabled: true,
    nudge_time: '09:00',
    daily_reflection_time: '00:00',
    weekly_summary_day: '0',
    weekly_summary_time: '00:00',
  });
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [refreshingStatus, setRefreshingStatus] = useState(false);
  const { toast } = useToast();

  const fetchData = async () => {
    try {
      setLoading(true);
      
      const savedTelegramId = getTelegramId();
      if (savedTelegramId) {
        setSettings(prev => ({ ...prev, telegram_id: savedTelegramId }));
      }
      
      const [settingsData, statusData] = await Promise.all([
        fetchAPI('/api/settings').catch(() => null),
        fetchAPI('/api/health').catch(() => null),
      ]);
      if (settingsData) {
        setSettings({
          ...settingsData,
          telegram_id: savedTelegramId || settingsData.telegram_id || ''
        });
      }
      if (statusData) {
        setStatus(statusData);
      }
    } catch (err) {
      console.error('Failed to load settings:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const refreshStatus = async () => {
    setRefreshingStatus(true);
    try {
      const statusData = await fetchAPI('/api/health');
      setStatus(statusData);
    } catch (err) {
      console.error('Failed to refresh status:', err);
    } finally {
      setRefreshingStatus(false);
    }
  };

  const handleSave = async () => {
    if (!settings.telegram_id) {
      toast({
        title: 'Telegram ID required',
        description: 'Please enter your Telegram ID to use the dashboard',
        variant: 'destructive',
      });
      return;
    }
    
    try {
      setSaving(true);
      
      setTelegramId(settings.telegram_id);
      
      try {
        await fetchAPI('/api/settings', {
          method: 'PUT',
          body: JSON.stringify(settings),
        });
      } catch (backendErr) {
        console.warn('Backend settings save failed (user may need to /start bot first):', backendErr);
      }
      
      toast({
        title: 'Settings saved!',
        description: 'Your preferences have been updated. Refresh pages to see changes.',
      });
    } catch (err) {
      toast({
        title: 'Failed to save',
        description: err instanceof Error ? err.message : 'Could not save settings',
        variant: 'destructive',
      });
    } finally {
      setSaving(false);
    }
  };

  const StatusIndicator = ({ connected, label }: { connected: boolean; label: string }) => (
    <motion.div 
      whileHover={{ scale: 1.02 }}
      className={`flex items-center justify-between p-3 rounded-xl transition-all ${
        connected 
          ? 'bg-green-500/10 border border-green-500/20' 
          : 'bg-red-500/10 border border-red-500/20'
      }`}
    >
      <span className="text-sm font-medium">{label}</span>
      <div className="flex items-center gap-2">
        {connected ? (
          <>
            <CheckCircle2 className="h-4 w-4 text-green-500" />
            <span className="text-xs text-green-500 font-medium">Online</span>
          </>
        ) : (
          <>
            <XCircle className="h-4 w-4 text-red-500" />
            <span className="text-xs text-red-500 font-medium">Offline</span>
          </>
        )}
      </div>
    </motion.div>
  );

  return (
    <div className="space-y-8 pb-8">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-card via-card to-muted/30 p-8 border border-border/30"
      >
        <div className="absolute -top-24 -right-24 w-48 h-48 bg-primary/10 rounded-full blur-3xl" />
        <div className="absolute -bottom-24 -left-24 w-48 h-48 bg-accent/10 rounded-full blur-3xl" />
        
        <div className="relative flex flex-col md:flex-row md:items-center md:justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <motion.div
                initial={{ scale: 0, rotate: -180 }}
                animate={{ scale: 1, rotate: 0 }}
                transition={{ type: 'spring', stiffness: 200, damping: 15 }}
                className="p-2.5 rounded-xl bg-primary/10 border border-primary/20"
              >
                <Cog className="h-6 w-6 text-primary" />
              </motion.div>
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight">
                <span className="gradient-text">Settings</span>
              </h1>
            </div>
            <p className="text-muted-foreground max-w-md">
              Configure your Weekly Progress Agent
            </p>
          </div>
          
          <Button 
            onClick={handleSave} 
            disabled={saving} 
            className="w-fit btn-magnetic rounded-xl bg-gradient-to-r from-primary to-primary/80 shadow-lg shadow-primary/25"
          >
            {saving ? (
              <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            Save Changes
          </Button>
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        <Card className="premium-card">
          <CardHeader className="pb-3 border-b border-border/30">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-primary/10 border border-primary/20">
                  <Server className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <CardTitle className="text-lg">System Status</CardTitle>
                  <CardDescription className="text-xs">Monitor your agent's health</CardDescription>
                </div>
              </div>
              <Button 
                variant="outline" 
                size="sm" 
                onClick={refreshStatus}
                disabled={refreshingStatus}
                className="rounded-xl border-border/50 hover:border-primary/50"
              >
                <RefreshCw className={`mr-2 h-4 w-4 ${refreshingStatus ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
            </div>
          </CardHeader>
          <CardContent className="pt-6">
            {status ? (
              <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
                <StatusIndicator connected={status.database_connected} label="Database" />
                <StatusIndicator connected={status.vector_store_connected} label="Vector Store" />
                <StatusIndicator connected={status.telegram_connected} label="Telegram Bot" />
                <StatusIndicator connected={status.scheduler_running} label="Scheduler" />
              </div>
            ) : (
              <div className="flex items-center justify-center gap-2 py-8 text-muted-foreground">
                <AlertCircle className="h-5 w-5" />
                <span>Unable to fetch system status</span>
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>

      <motion.div 
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        className="grid gap-6 lg:grid-cols-2"
      >
        {/* Telegram Settings */}
        <motion.div variants={cardVariants}>
          <Card className="premium-card h-full">
            <CardHeader className="pb-3 border-b border-border/30">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-500/20 border border-blue-500/20">
                  <Bot className="h-4 w-4 text-blue-500" />
                </div>
                <div>
                  <CardTitle className="text-lg">Telegram Bot</CardTitle>
                  <CardDescription className="text-xs">Configure your Telegram integration</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-5 pt-6">
              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center gap-2">
                  Your Telegram ID
                  <Badge variant="outline" className="text-xs rounded-lg border-primary/30 text-primary">Required</Badge>
                </label>
                <Input
                  value={settings.telegram_id}
                  onChange={(e) =>
                    setSettings({ ...settings, telegram_id: e.target.value })
                  }
                  placeholder="Enter your Telegram user ID"
                  className="rounded-xl"
                />
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  <HelpCircle className="h-3 w-3" />
                  Send /start to @your_bot to get your ID
                </p>
              </div>
            </CardContent>
          </Card>
        </motion.div>

        {/* Post Settings */}
        <motion.div variants={cardVariants}>
          <Card className="premium-card h-full">
            <CardHeader className="pb-3 border-b border-border/30">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-[#0A66C2]/10 border border-[#0A66C2]/20">
                  <Linkedin className="h-4 w-4 text-[#0A66C2]" />
                </div>
                <div>
                  <CardTitle className="text-lg">LinkedIn Posts</CardTitle>
                  <CardDescription className="text-xs">Customize your generated posts</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-5 pt-6">
              <div className="space-y-3">
                <label className="text-sm font-medium">Default Tone</label>
                <div className="grid grid-cols-3 gap-2">
                  {tones.map((tone) => {
                    const isSelected = settings.default_tone === tone.value;
                    return (
                      <motion.button
                        key={tone.value}
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => setSettings({ ...settings, default_tone: tone.value })}
                        className={`p-3 rounded-xl border-2 transition-all text-center ${
                          isSelected 
                            ? 'border-primary bg-primary/5' 
                            : 'border-border/50 hover:border-primary/30'
                        }`}
                      >
                        <div className="text-xl mb-1">{tone.emoji}</div>
                        <div className="text-xs font-medium">{tone.label}</div>
                      </motion.button>
                    );
                  })}
                </div>
              </div>
              <Separator className="bg-border/30" />
              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-muted-foreground" />
                  Weekly Summary Day
                </label>
                <Select
                  value={settings.weekly_summary_day}
                  onValueChange={(value) =>
                    setSettings({ ...settings, weekly_summary_day: value })
                  }
                >
                  <SelectTrigger className="rounded-xl">
                    <SelectValue placeholder="Select day" />
                  </SelectTrigger>
                  <SelectContent>
                    {weekdays.map((day) => (
                      <SelectItem key={day.value} value={day.value}>
                        {day.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>
        </motion.div>

        {/* Schedule Settings */}
        <motion.div variants={cardVariants}>
          <Card className="premium-card h-full">
            <CardHeader className="pb-3 border-b border-border/30">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 border border-purple-500/20">
                  <Clock className="h-4 w-4 text-purple-500" />
                </div>
                <div>
                  <CardTitle className="text-lg">Schedule</CardTitle>
                  <CardDescription className="text-xs">Configure automated task timing</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-5 pt-6">
              <div className="space-y-2">
                <label className="text-sm font-medium">Daily Reflection Time</label>
                <Input
                  type="time"
                  value={settings.daily_reflection_time}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      daily_reflection_time: e.target.value,
                    })
                  }
                  className="rounded-xl"
                />
                <p className="text-xs text-muted-foreground">
                  When to receive your daily summary
                </p>
              </div>
              <Separator className="bg-border/30" />
              <div className="space-y-2">
                <label className="text-sm font-medium">Weekly Summary Time</label>
                <Input
                  type="time"
                  value={settings.weekly_summary_time}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      weekly_summary_time: e.target.value,
                    })
                  }
                  className="rounded-xl"
                />
                <p className="text-xs text-muted-foreground">
                  When to generate your weekly LinkedIn post
                </p>
              </div>
            </CardContent>
          </Card>
        </motion.div>

        {/* Nudge Settings */}
        <motion.div variants={cardVariants}>
          <Card className="premium-card h-full">
            <CardHeader className="pb-3 border-b border-border/30">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 border border-amber-500/20">
                  <Bell className="h-4 w-4 text-amber-500" />
                </div>
                <div>
                  <CardTitle className="text-lg">Reminders</CardTitle>
                  <CardDescription className="text-xs">Configure nudge notifications</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-5 pt-6">
              <div className="flex items-center justify-between p-4 rounded-xl bg-muted/30 border border-border/30">
                <div className="flex items-center gap-3">
                  <Zap className="h-5 w-5 text-amber-500" />
                  <div>
                    <p className="text-sm font-medium">Enable Nudges</p>
                    <p className="text-xs text-muted-foreground">
                      Receive reminders to log your progress
                    </p>
                  </div>
                </div>
                <Switch
                  checked={settings.nudge_enabled}
                  onCheckedChange={(checked) =>
                    setSettings({ ...settings, nudge_enabled: checked })
                  }
                />
              </div>
              <Separator className="bg-border/30" />
              <div className="space-y-2">
                <label className="text-sm font-medium">Morning Nudge Time</label>
                <Input
                  type="time"
                  value={settings.nudge_time}
                  onChange={(e) =>
                    setSettings({ ...settings, nudge_time: e.target.value })
                  }
                  disabled={!settings.nudge_enabled}
                  className="rounded-xl disabled:opacity-50"
                />
                <p className="text-xs text-muted-foreground">
                  When to receive your daily reminder
                </p>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      </motion.div>

      {/* Save Button Mobile */}
      <motion.div 
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.6 }}
        className="flex justify-end md:hidden"
      >
        <Button 
          onClick={handleSave} 
          disabled={saving} 
          className="w-full btn-magnetic rounded-xl bg-gradient-to-r from-primary to-primary/80"
        >
          {saving ? (
            <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          Save Changes
        </Button>
      </motion.div>
    </div>
  );
}
