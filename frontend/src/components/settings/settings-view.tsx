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
import { Separator } from '@/components/ui/separator';
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
} from 'lucide-react';
import { fetchAPI, getTelegramId, setTelegramId } from '@/lib/utils';
import { useToast } from '@/components/ui/use-toast';

interface SettingsData {
  telegram_id: string;
  timezone: string;
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

const timezones = [
  'UTC',
  'America/New_York',
  'America/Los_Angeles',
  'America/Chicago',
  'America/Denver',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Asia/Kolkata',
  'Australia/Sydney',
];

const tones = [
  { value: 'professional', label: 'Professional' },
  { value: 'casual', label: 'Casual' },
  { value: 'inspirational', label: 'Inspirational' },
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

export function SettingsView() {
  const [settings, setSettings] = useState<SettingsData>({
    telegram_id: '',
    timezone: 'UTC',
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
  const { toast } = useToast();

  useEffect(() => {
    async function fetchData() {
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
    }
    fetchData();
  }, []);

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
        title: 'Settings saved',
        description: 'Your Telegram ID has been saved. Refresh other pages to see your data.',
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

  const StatusIndicator = ({ connected }: { connected: boolean }) => (
    <div className="flex items-center gap-2">
      {connected ? (
        <>
          <div className="h-2 w-2 rounded-full bg-green-500" />
          <span className="text-sm text-green-600">Connected</span>
        </>
      ) : (
        <>
          <div className="h-2 w-2 rounded-full bg-red-500" />
          <span className="text-sm text-red-600">Disconnected</span>
        </>
      )}
    </div>
  );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Settings</h2>
        <p className="text-muted-foreground">
          Configure your Weekly Progress Agent
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Telegram Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bot className="h-5 w-5" />
              Telegram Bot
            </CardTitle>
            <CardDescription>
              Configure your Telegram integration
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Your Telegram ID</label>
              <Input
                value={settings.telegram_id}
                onChange={(e) =>
                  setSettings({ ...settings, telegram_id: e.target.value })
                }
                placeholder="Enter your Telegram user ID"
              />
              <p className="text-xs text-muted-foreground">
                Send /start to the bot to get your ID
              </p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Timezone</label>
              <Select
                value={settings.timezone}
                onValueChange={(value) =>
                  setSettings({ ...settings, timezone: value })
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select timezone" />
                </SelectTrigger>
                <SelectContent>
                  {timezones.map((tz) => (
                    <SelectItem key={tz} value={tz}>
                      {tz}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* Post Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Linkedin className="h-5 w-5" />
              LinkedIn Posts
            </CardTitle>
            <CardDescription>
              Customize your generated posts
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Default Tone</label>
              <Select
                value={settings.default_tone}
                onValueChange={(value) =>
                  setSettings({ ...settings, default_tone: value })
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select tone" />
                </SelectTrigger>
                <SelectContent>
                  {tones.map((tone) => (
                    <SelectItem key={tone.value} value={tone.value}>
                      {tone.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Weekly Summary Day</label>
              <Select
                value={settings.weekly_summary_day}
                onValueChange={(value) =>
                  setSettings({ ...settings, weekly_summary_day: value })
                }
              >
                <SelectTrigger>
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

        {/* Schedule Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock className="h-5 w-5" />
              Schedule
            </CardTitle>
            <CardDescription>
              Configure automated tasks timing
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
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
              />
            </div>
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
              />
            </div>
          </CardContent>
        </Card>

        {/* Nudge Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bell className="h-5 w-5" />
              Nudges & Reminders
            </CardTitle>
            <CardDescription>
              Configure reminder notifications
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Enable Nudges</p>
                <p className="text-xs text-muted-foreground">
                  Receive reminders to log your progress
                </p>
              </div>
              <Button
                variant={settings.nudge_enabled ? 'default' : 'outline'}
                size="sm"
                onClick={() =>
                  setSettings({
                    ...settings,
                    nudge_enabled: !settings.nudge_enabled,
                  })
                }
              >
                {settings.nudge_enabled ? 'Enabled' : 'Disabled'}
              </Button>
            </div>
            <Separator />
            <div className="space-y-2">
              <label className="text-sm font-medium">Morning Nudge Time</label>
              <Input
                type="time"
                value={settings.nudge_time}
                onChange={(e) =>
                  setSettings({ ...settings, nudge_time: e.target.value })
                }
                disabled={!settings.nudge_enabled}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* System Status */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            System Status
          </CardTitle>
          <CardDescription>
            Monitor your agent's health and connectivity
          </CardDescription>
        </CardHeader>
        <CardContent>
          {status ? (
            <div className="grid gap-4 md:grid-cols-4">
              <div className="space-y-1">
                <p className="text-sm font-medium">Database</p>
                <StatusIndicator connected={status.database_connected} />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium">Vector Store</p>
                <StatusIndicator connected={status.vector_store_connected} />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium">Telegram</p>
                <StatusIndicator connected={status.telegram_connected} />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium">Scheduler</p>
                <StatusIndicator connected={status.scheduler_running} />
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-muted-foreground">
              <AlertCircle className="h-4 w-4" />
              <span className="text-sm">Unable to fetch system status</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Save Button */}
      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={saving}>
          {saving ? (
            <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          Save Settings
        </Button>
      </div>
    </div>
  );
}
