'use client';

import {
  Bell,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Download,
  Edit3,
  Eye,
  EyeOff,
  Flag,
  NotebookPen,
  Pause,
  Pin,
  Plus,
  Save,
  Trash2,
  Utensils,
} from 'lucide-react';
import {
  type FormEvent,
  type ReactNode,
  useState,
} from 'react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

import { API_URL, fetchAPI, formatDateTime } from '@/lib/utils';
import { useApiResource } from '@/lib/use-api-resource';
import type {
  Goal,
  LedgerEntry,
  LedgerSummary,
  Note,
  NutritionItem,
  NutritionLog,
  NutritionPreferences,
  NutritionSummary,
  PrivateFact,
  PrivateFactType,
  RevealedPrivateFact,
  Reminder,
  SchedulePreferences,
  ScreenName,
  WorkLog,
} from '@/lib/public-types';
import {
  buttonClassName,
  destructiveButtonClassName,
  EmptyState,
  ErrorState,
  FormField,
  inputClassName,
  LoadingState,
  ScreenHeading,
  secondaryButtonClassName,
} from './screen-kit';

const timezoneAliases: Record<string, string> = {
  'Asia/Calcutta': 'Asia/Kolkata',
};
const reportedTimezone =
  Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
const localTimezone = timezoneAliases[reportedTimezone] || reportedTimezone;

function localDate(date = new Date()): string {
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60_000)
    .toISOString()
    .slice(0, 10);
}

function localDateTimeValue(isoValue: string | null): string {
  if (!isoValue) return '';
  const date = new Date(isoValue);
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60_000)
    .toISOString()
    .slice(0, 16);
}

function idempotencyKey(prefix: string): string {
  return `${prefix}:${crypto.randomUUID()}`;
}

function parseTags(value: string): string[] {
  return [...new Set(value.split(',').map((tag) => tag.trim().toLowerCase()).filter(Boolean))].slice(0, 20);
}

function formatDecimal(value: string): string {
  return value.includes('.') ? value.replace(/\.?0+$/, '') : value;
}

function Card({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <article className={`rounded-xl border bg-card p-4 shadow-sm ${className}`}>
      {children}
    </article>
  );
}

function MutationError({ message }: { message: string | null }) {
  return message ? (
    <p className="text-sm text-destructive" role="alert">
      {message}
    </p>
  ) : null;
}

export function HomeScreen({
  onNavigate,
}: {
  onNavigate: (screen: ScreenName) => void;
}) {
  const today = localDate();
  const monthStart = `${today.slice(0, 7)}-01`;
  const resource = useApiResource(async () => {
    const [
      work,
      reminders,
      money,
      nutrition,
      goals,
    ] = await Promise.all([
      fetchAPI<WorkLog[]>(
        `/api/v2/work-logs?start_date=${today}&end_date=${today}&limit=5`,
      ),
      fetchAPI<Reminder[]>(
        '/api/v2/reminders?enabled=true&limit=5',
      ),
      fetchAPI<LedgerSummary[]>(
        `/api/v2/ledger/summary?start_date=${monthStart}&end_date=${today}`,
      ),
      fetchAPI<NutritionSummary>(
        `/api/v2/nutrition/summary?start_date=${today}&end_date=${today}`,
      ),
      fetchAPI<Goal[]>('/api/v2/goals?status=active&limit=5'),
    ]);
    return { work, reminders, money, nutrition, goals };
  }, today);

  return (
    <>
      <ScreenHeading
        title="Today"
        description="A private overview derived from your confirmed records."
      />
      {resource.loading ? <LoadingState label="Loading today" /> : null}
      {resource.error ? (
        <ErrorState message={resource.error} retry={resource.reload} />
      ) : null}
      {resource.data ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Metric
              label="Work logs"
              value={String(resource.data.work.length)}
            />
            <Metric
              label="Pending reminders"
              value={String(resource.data.reminders.length)}
            />
            <Metric
              label="Calories"
              value={`≈ ${resource.data.nutrition.total_calories}`}
            />
            <Metric
              label="Protein"
              value={`≈ ${resource.data.nutrition.total_protein_grams} g`}
            />
          </div>
          <Card>
            <h2 className="font-semibold">Money this month</h2>
            {resource.data.money.length ? (
              <ul className="mt-2 space-y-1 text-sm">
                {resource.data.money.map((item) => (
                  <li key={item.currency}>
                    Income {moneyValue(item.income_minor, item.currency)} / spent{' '}
                    {moneyValue(item.expense_minor, item.currency)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">
                No transactions this month.
              </p>
            )}
          </Card>
          <Card>
            <h2 className="font-semibold">Active goals</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              {resource.data.goals.length
                ? `${resource.data.goals.length} active`
                : 'No active goals'}
            </p>
          </Card>
          <div>
            <h2 className="mb-2 text-sm font-semibold">Quick add</h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                ['work', 'Work log', Plus],
                ['notes', 'Note', NotebookPen],
                ['money', 'Expense', CircleDollarSign],
                ['nutrition', 'Food', Utensils],
              ].map(([screen, label, Icon]) => (
                <button
                  key={String(screen)}
                  type="button"
                  onClick={() => onNavigate(screen as ScreenName)}
                  className={secondaryButtonClassName}
                >
                  <Icon className="mr-2 h-4 w-4" aria-hidden />
                  {String(label)}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 break-words text-xl font-bold">{value}</p>
    </Card>
  );
}

export function WorkLogsScreen() {
  const resource = useApiResource(
    () => fetchAPI<WorkLog[]>('/api/v2/work-logs?limit=100'),
    '',
  );
  const [text, setText] = useState('');
  const [category, setCategory] = useState('');
  const [tags, setTags] = useState('');
  const [editing, setEditing] = useState<WorkLog | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await fetchAPI(`/api/v2/work-logs/${editing.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            version: editing.version,
            original_text: text,
            category: category || null,
            tags: parseTags(tags),
          }),
        });
      } else {
        await fetchAPI('/api/v2/work-logs', {
          method: 'POST',
          body: JSON.stringify({
            original_text: text,
            category: category || null,
            tags: parseTags(tags),
            timezone: localTimezone,
            capture_source: 'mini_app',
            idempotency_key: idempotencyKey('work'),
          }),
        });
      }
      setText('');
      setCategory('');
      setTags('');
      setEditing(null);
      setDialogOpen(false);
      await resource.reload();
    } catch (mutationError) {
      setError(
        mutationError instanceof Error
          ? mutationError.message
          : 'Unable to save work log.',
      );
    } finally {
      setSaving(false);
    }
  }

  async function remove(record: WorkLog) {
    if (!window.confirm('Delete this work log permanently?')) return;
    await fetchAPI(`/api/v2/work-logs/${record.id}`, { method: 'DELETE' });
    await resource.reload();
  }

  return (
    <>
      <ScreenHeading
        title="Work logs"
        description="Review your progress history and activity patterns."
        action={<button type="button" className={buttonClassName} onClick={() => { setEditing(null); setText(''); setCategory(''); setTags(''); setDialogOpen(true); }}><Plus className="mr-2 h-4 w-4" aria-hidden />Add</button>}
      />
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader><DialogTitle>{editing ? 'Edit work log' : 'Add work log'}</DialogTitle><DialogDescription>Capture a completed task, learning, or blocker.</DialogDescription></DialogHeader>
      <form onSubmit={submit} className="space-y-3">
        <FormField label="What did you complete?" htmlFor="work-text">
          <textarea
            id="work-text"
            value={text}
            onChange={(event) => setText(event.target.value)}
            required
            maxLength={10_000}
            rows={3}
            className={inputClassName}
          />
        </FormField>
        <FormField label="Category (optional)" htmlFor="work-category">
          <input
            id="work-category"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            maxLength={64}
            className={inputClassName}
          />
        </FormField>
        <FormField label="Tags (optional, comma separated)" htmlFor="work-tags">
          <input
            id="work-tags"
            value={tags}
            onChange={(event) => setTags(event.target.value)}
            maxLength={500}
            className={inputClassName}
          />
        </FormField>
        <MutationError message={error} />
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={saving} className={buttonClassName}>
            <Save className="mr-2 h-4 w-4" aria-hidden />
            {editing ? 'Save edit' : 'Add work log'}
          </button>
          {editing ? (
            <button
              type="button"
              className={secondaryButtonClassName}
              onClick={() => {
                setEditing(null);
                setText('');
                setCategory('');
                setTags('');
              }}
            >
              Cancel
            </button>
          ) : null}
        </div>
      </form>
        </DialogContent>
      </Dialog>
      <ResourceList resource={resource} emptyLabel="No work logs yet.">
        {(resource.data || []).map((record) => (
          <Card key={record.id}>
            <p className="whitespace-pre-wrap break-words text-sm">
              {record.original_text}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              {record.category || 'Uncategorized'} ·{' '}
              {formatDateTime(record.logged_at_utc)}
            </p>
            {record.tags.length ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Tags: {record.tags.join(', ')}
              </p>
            ) : null}
            <RecordActions
              onEdit={() => {
                setEditing(record);
                setText(record.original_text);
                setCategory(record.category || '');
                setTags(record.tags.join(', '));
                setDialogOpen(true);
              }}
              onDelete={() => void remove(record)}
            />
          </Card>
        ))}
      </ResourceList>
    </>
  );
}

export function NotesScreen() {
  const resource = useApiResource(
    () => fetchAPI<Note[]>('/api/v2/notes?limit=100'),
    '',
  );
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [tags, setTags] = useState('');
  const [editing, setEditing] = useState<Note | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      if (editing) {
        await fetchAPI(`/api/v2/notes/${editing.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            version: editing.version,
            title: title.trim() || body.split('\n')[0].slice(0, 80),
            body,
            tags: parseTags(tags),
          }),
        });
      } else {
        await fetchAPI('/api/v2/notes', {
          method: 'POST',
          body: JSON.stringify({
            title: title.trim() || null,
            body,
            tags: parseTags(tags),
            capture_source: 'mini_app',
            idempotency_key: idempotencyKey('note'),
          }),
        });
      }
      setTitle('');
      setBody('');
      setTags('');
      setEditing(null);
      setDialogOpen(false);
      await resource.reload();
    } catch (mutationError) {
      setError(
        mutationError instanceof Error
          ? mutationError.message
          : 'Unable to save note.',
      );
    }
  }

  async function patch(record: Note, values: Record<string, unknown>) {
    await fetchAPI(`/api/v2/notes/${record.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ version: record.version, ...values }),
    });
    await resource.reload();
  }

  async function remove(record: Note) {
    if (!window.confirm('Delete this note permanently?')) return;
    await fetchAPI(`/api/v2/notes/${record.id}`, { method: 'DELETE' });
    await resource.reload();
  }

  return (
    <>
      <ScreenHeading title="Notes" description="Searchable private notes, with important items pinned first." action={<button type="button" className={buttonClassName} onClick={() => { setEditing(null); setTitle(''); setBody(''); setTags(''); setDialogOpen(true); }}><Plus className="mr-2 h-4 w-4" aria-hidden />Add</button>} />
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader><DialogTitle>{editing ? 'Edit note' : 'Add note'}</DialogTitle><DialogDescription>Keep a private thought, reference, or follow-up.</DialogDescription></DialogHeader>
      <form onSubmit={submit} className="space-y-3">
        <FormField label="Title (optional)" htmlFor="note-title">
          <input
            id="note-title"
            maxLength={255}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className={inputClassName}
          />
        </FormField>
        <FormField label="Note" htmlFor="note-body">
          <textarea
            id="note-body"
            required
            maxLength={10_000}
            rows={3}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            className={inputClassName}
          />
        </FormField>
        <FormField label="Tags (optional, comma separated)" htmlFor="note-tags">
          <input
            id="note-tags"
            value={tags}
            onChange={(event) => setTags(event.target.value)}
            maxLength={500}
            className={inputClassName}
          />
        </FormField>
        <MutationError message={error} />
        <button type="submit" className={buttonClassName}>
          {editing ? 'Save edit' : 'Add note'}
        </button>
      </form>
        </DialogContent>
      </Dialog>
      <ResourceList resource={resource} emptyLabel="No notes yet.">
        {(resource.data || []).map((record) => (
          <Card key={record.id}>
            <div className="flex items-start gap-2">
              {record.pinned ? (
                <Pin className="mt-0.5 h-4 w-4 text-primary" aria-label="Pinned" />
              ) : null}
              <div className="min-w-0 flex-1">
                <h2 className="break-words font-semibold">{record.title}</h2>
                <p className="mt-1 whitespace-pre-wrap break-words text-sm text-muted-foreground">
                  {record.body}
                </p>
                {record.tags.length ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Tags: {record.tags.join(', ')}
                  </p>
                ) : null}
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                className={secondaryButtonClassName}
                onClick={() => void patch(record, { pinned: !record.pinned })}
                aria-label={record.pinned ? 'Unpin note' : 'Pin note'}
              >
                <Pin className="mr-2 h-4 w-4" aria-hidden />
                {record.pinned ? 'Unpin' : 'Pin'}
              </button>
              <RecordActions
                onEdit={() => {
                  setEditing(record);
                  setTitle(record.title);
                  setBody(record.body);
                  setTags(record.tags.join(', '));
                  setDialogOpen(true);
                }}
                onDelete={() => void remove(record)}
              />
            </div>
          </Card>
        ))}
      </ResourceList>
    </>
  );
}

export function RemindersScreen() {
  const resource = useApiResource(
    () => fetchAPI<Reminder[]>('/api/v2/reminders?limit=100'),
    '',
  );
  const [title, setTitle] = useState('');
  const [scheduleType, setScheduleType] =
    useState<Reminder['schedule_type']>('once');
  const [startAt, setStartAt] = useState('');
  const [editing, setEditing] = useState<Reminder | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const local = new Date(startAt);
      const weekday =
        scheduleType === 'weekly'
          ? local.getDay() === 0
            ? 6
            : local.getDay() - 1
          : null;
      if (editing) {
        await fetchAPI(`/api/v2/reminders/${editing.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            version: editing.version,
            title,
            start_at_local: startAt,
            timezone: localTimezone,
            weekday,
          }),
        });
      } else {
        await fetchAPI('/api/v2/reminders', {
          method: 'POST',
          body: JSON.stringify({
            title,
            schedule_type: scheduleType,
            start_at_local: startAt,
            timezone: localTimezone,
            weekday,
            idempotency_key: idempotencyKey('reminder'),
          }),
        });
      }
      setTitle('');
      setStartAt('');
      setEditing(null);
      setDialogOpen(false);
      await resource.reload();
    } catch (mutationError) {
      setError(
        mutationError instanceof Error
          ? mutationError.message
          : 'Unable to create reminder.',
      );
    }
  }

  async function toggle(record: Reminder) {
    await fetchAPI(`/api/v2/reminders/${record.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        version: record.version,
        enabled: !record.enabled,
      }),
    });
    await resource.reload();
  }

  async function remove(record: Reminder) {
    if (!window.confirm('Delete this reminder permanently?')) return;
    await fetchAPI(`/api/v2/reminders/${record.id}`, { method: 'DELETE' });
    await resource.reload();
  }

  return (
    <>
      <ScreenHeading
        title="Reminders"
        description="Upcoming and recurring schedules in your timezone."
        action={<button type="button" className={buttonClassName} onClick={() => { setEditing(null); setTitle(''); setStartAt(''); setScheduleType('once'); setDialogOpen(true); }}><Plus className="mr-2 h-4 w-4" aria-hidden />Add</button>}
      />
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader><DialogTitle>{editing ? 'Edit reminder' : 'Add reminder'}</DialogTitle><DialogDescription>Schedule a one-time or recurring notification.</DialogDescription></DialogHeader>
      <form onSubmit={submit} className="space-y-3">
        {editing ? (
          <p className="text-sm font-medium">Editing reminder</p>
        ) : null}
        <FormField label="Reminder" htmlFor="reminder-title">
          <input
            id="reminder-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            maxLength={255}
            className={inputClassName}
          />
        </FormField>
        <FormField label="Frequency" htmlFor="reminder-frequency">
          <select
            id="reminder-frequency"
            value={scheduleType}
            onChange={(event) =>
              setScheduleType(
                event.target.value as Reminder['schedule_type'],
              )
            }
            className={inputClassName}
            disabled={Boolean(editing)}
          >
            <option value="once">One time</option>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
          </select>
        </FormField>
        <FormField label="First occurrence" htmlFor="reminder-start">
          <input
            id="reminder-start"
            type="datetime-local"
            value={startAt}
            onChange={(event) => setStartAt(event.target.value)}
            required
            className={inputClassName}
          />
        </FormField>
        <MutationError message={error} />
        <button type="submit" className={buttonClassName}>
          <Bell className="mr-2 h-4 w-4" aria-hidden />
          {editing ? 'Save reminder' : 'Add reminder'}
        </button>
        {editing ? (
          <button
            type="button"
            className={`${secondaryButtonClassName} ml-2`}
            onClick={() => {
              setEditing(null);
              setTitle('');
              setStartAt('');
              setScheduleType('once');
            }}
          >
            Cancel
          </button>
        ) : null}
      </form>
        </DialogContent>
      </Dialog>
      <ResourceList resource={resource} emptyLabel="No reminders yet.">
        {(resource.data || []).map((record) => (
          <Card key={record.id}>
            <h2 className="break-words font-semibold">{record.title}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {record.schedule_type} ·{' '}
              {record.next_run_at_utc
                ? formatDateTime(record.next_run_at_utc)
                : 'No next run'}{' '}
              · {record.enabled ? 'Active' : 'Paused'}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                className={secondaryButtonClassName}
                onClick={() => {
                  setEditing(record);
                  setTitle(record.title);
                  setScheduleType(record.schedule_type);
                  setStartAt(localDateTimeValue(record.next_run_at_utc));
                  setDialogOpen(true);
                }}
              >
                <Edit3 className="mr-2 h-4 w-4" aria-hidden />
                Edit
              </button>
              <button
                type="button"
                className={secondaryButtonClassName}
                onClick={() => void toggle(record)}
              >
                <Pause className="mr-2 h-4 w-4" aria-hidden />
                {record.enabled ? 'Pause' : 'Resume'}
              </button>
              <button
                type="button"
                className={destructiveButtonClassName}
                onClick={() => void remove(record)}
                aria-label={`Delete reminder ${record.title}`}
              >
                <Trash2 className="mr-2 h-4 w-4" aria-hidden />
                Delete
              </button>
            </div>
          </Card>
        ))}
      </ResourceList>
    </>
  );
}

function moneyValue(amountMinor: number, currency: string): string {
  try {
    const digits = new Intl.NumberFormat('en', {
      style: 'currency',
      currency,
    }).resolvedOptions().maximumFractionDigits ?? 2;
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
    }).format(amountMinor / 10 ** digits);
  } catch {
    return `${amountMinor} ${currency} minor units`;
  }
}

function currencyFractionDigits(currency: string): number | null {
  try {
    return new Intl.NumberFormat('en', {
      style: 'currency',
      currency,
    }).resolvedOptions().maximumFractionDigits ?? null;
  } catch {
    return null;
  }
}

function ledgerCategoryClass(category: string | null): string {
  const palette = [
    'bg-violet-500/10 text-violet-700 dark:text-violet-300',
    'bg-blue-500/10 text-blue-700 dark:text-blue-300',
    'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
    'bg-amber-500/10 text-amber-700 dark:text-amber-300',
    'bg-rose-500/10 text-rose-700 dark:text-rose-300',
    'bg-cyan-500/10 text-cyan-700 dark:text-cyan-300',
  ];
  const normalized = (category || 'uncategorized').toLowerCase();
  const hash = [...normalized].reduce(
    (total, character) => total + character.charCodeAt(0),
    0,
  );
  return palette[hash % palette.length];
}

export function MoneyScreen() {
  const [rangeMode, setRangeMode] = useState<'all' | 'month'>('all');
  const [selectedMonth, setSelectedMonth] = useState(localDate().slice(0, 7));
  const [year, month] = selectedMonth.split('-').map(Number);
  const monthStart = `${selectedMonth}-01`;
  const monthEnd = localDate(new Date(year, month, 0));
  const resource = useApiResource(async () => {
    const rangeQuery = rangeMode === 'month'
      ? `start_date=${monthStart}&end_date=${monthEnd}&`
      : '';
    const [entries, totals] = await Promise.all([
      fetchAPI<LedgerEntry[]>(
        `/api/v2/ledger?${rangeQuery}limit=100`,
      ),
      fetchAPI<LedgerSummary[]>(
        `/api/v2/ledger/summary${rangeMode === 'month' ? `?start_date=${monthStart}&end_date=${monthEnd}` : ''}`,
      ),
    ]);
    return { entries, totals };
  }, `${rangeMode}:${selectedMonth}`);
  const [direction, setDirection] =
    useState<LedgerEntry['direction']>('expense');
  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState('INR');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('');
  const [editing, setEditing] = useState<LedgerEntry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const allowedFractionDigits = currencyFractionDigits(currency);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const enteredFractionDigits = amount.includes('.')
      ? amount.split('.')[1].length
      : 0;
    if (allowedFractionDigits === null) {
      setError('Enter a valid three-letter currency code, such as INR.');
      return;
    }
    if (enteredFractionDigits > allowedFractionDigits) {
      setError(
        `${currency} supports at most ${allowedFractionDigits} decimal place${
          allowedFractionDigits === 1 ? '' : 's'
        }.`,
      );
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await fetchAPI(`/api/v2/ledger/${editing.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            version: editing.version,
            amount,
            currency,
            description,
            category: category || null,
          }),
        });
      } else {
        await fetchAPI('/api/v2/ledger', {
          method: 'POST',
          body: JSON.stringify({
            direction,
            amount,
            currency,
            description,
            category: category || null,
            timezone: localTimezone,
            capture_source: 'mini_app',
            idempotency_key: idempotencyKey('ledger'),
          }),
        });
      }
      setAmount('');
      setDescription('');
      setCategory('');
      setEditing(null);
      setDialogOpen(false);
      await resource.reload();
    } catch (mutationError) {
      setError(
        mutationError instanceof Error
          ? mutationError.message
          : 'Unable to save transaction.',
      );
    } finally {
      setSaving(false);
    }
  }

  async function remove(record: LedgerEntry) {
    if (!window.confirm('Delete this transaction permanently?')) return;
    await fetchAPI(`/api/v2/ledger/${record.id}`, { method: 'DELETE' });
    await resource.reload();
  }

  return (
    <>
      <ScreenHeading
        title="Money"
        description="Monthly income, spending, and cash-flow analytics."
        action={
          <button
            type="button"
            className={buttonClassName}
            onClick={() => {
              setEditing(null);
              setAmount('');
              setDescription('');
              setCategory('');
              setDialogOpen(true);
            }}
          >
            <Plus className="mr-2 h-4 w-4" aria-hidden />
            Add
          </button>
        }
      />
      <div className="mb-4 rounded-xl border bg-card p-3">
        <div className="grid grid-cols-2 gap-2" role="group" aria-label="Money history range">
          <button
            type="button"
            className={rangeMode === 'all' ? buttonClassName : secondaryButtonClassName}
            onClick={() => setRangeMode('all')}
          >
            All activity
          </button>
          <button
            type="button"
            className={rangeMode === 'month' ? buttonClassName : secondaryButtonClassName}
            onClick={() => setRangeMode('month')}
          >
            One month
          </button>
        </div>
        {rangeMode === 'month' ? (
          <label className="mt-3 flex items-center justify-between gap-3 text-sm">
            <span className="font-medium">Reporting month</span>
            <input
              type="month"
              aria-label="Reporting month"
              value={selectedMonth}
              onChange={(event) => setSelectedMonth(event.target.value)}
              className="min-h-11 rounded-lg border bg-background px-3 text-sm"
            />
          </label>
        ) : (
          <p className="mt-3 text-xs text-muted-foreground">
            Showing your latest 100 transactions across all dates.
          </p>
        )}
      </div>
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? 'Edit transaction' : 'Add transaction'}</DialogTitle>
            <DialogDescription>
              Record a private income or expense entry. No bank is connected.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
            <FormField label="Type" htmlFor="money-direction">
              <select
                id="money-direction"
                value={direction}
                onChange={(event) =>
                  setDirection(event.target.value as LedgerEntry['direction'])
                }
                className={inputClassName}
                disabled={Boolean(editing)}
              >
                <option value="expense">Expense</option>
                <option value="income">Income</option>
              </select>
            </FormField>
            <FormField label="Amount" htmlFor="money-amount">
              <input id="money-amount" type="number" min={allowedFractionDigits === 0 ? '1' : `0.${'0'.repeat(Math.max((allowedFractionDigits || 2) - 1, 0))}1`} step={allowedFractionDigits === 0 ? '1' : `0.${'0'.repeat(Math.max((allowedFractionDigits || 2) - 1, 0))}1`} required value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClassName} />
            </FormField>
            <FormField label="Currency" htmlFor="money-currency">
              <input id="money-currency" required minLength={3} maxLength={3} value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} className={inputClassName} />
            </FormField>
            <FormField label="Description" htmlFor="money-description">
              <input id="money-description" required maxLength={5_000} value={description} onChange={(event) => setDescription(event.target.value)} className={inputClassName} />
            </FormField>
            <FormField label="Category (optional)" htmlFor="money-category">
              <input id="money-category" maxLength={64} value={category} onChange={(event) => setCategory(event.target.value)} className={inputClassName} placeholder="Food, travel, bills" />
            </FormField>
            <div className="sm:col-span-2">
              <MutationError message={error} />
              <button type="submit" disabled={saving} className={`${buttonClassName} mt-2 w-full`}>
                {saving ? 'Savingâ€¦' : editing ? 'Save transaction' : 'Add transaction'}
              </button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      {resource.data?.totals.length ? (
        <div className="mb-5 grid gap-3 sm:grid-cols-2">
          {resource.data.totals.map((total) => (
            <Card key={total.currency}>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{total.currency} {rangeMode === 'month' ? 'monthly' : 'all-time'} flow</p>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                <div><p className="text-xs text-muted-foreground">Income</p><p className="font-semibold text-emerald-600">{moneyValue(total.income_minor, total.currency)}</p></div>
                <div><p className="text-xs text-muted-foreground">Spent</p><p className="font-semibold text-destructive">{moneyValue(total.expense_minor, total.currency)}</p></div>
                <div><p className="text-xs text-muted-foreground">Net</p><p className="font-semibold">{moneyValue(total.income_minor - total.expense_minor, total.currency)}</p></div>
              </div>
            </Card>
          ))}
        </div>
      ) : null}
      <ResourceList
        resource={{
          ...resource,
          data: resource.data?.entries || null,
        }}
        emptyLabel="No transactions yet."
      >
        {(resource.data?.entries || []).map((record) => (
          <Card key={record.id}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="break-words font-semibold">
                  {record.description}
                </h2>
                <p className="text-sm text-muted-foreground">
                  {record.direction} · {record.user_local_date}
                </p>
                <span className={`mt-2 inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${ledgerCategoryClass(record.category)}`}>
                  {record.category || 'Uncategorized'}
                </span>
              </div>
              <p className="shrink-0 font-semibold">
                {moneyValue(record.amount_minor, record.currency)}
              </p>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                className={secondaryButtonClassName}
                onClick={() => {
                  const digits =
                    new Intl.NumberFormat('en', {
                      style: 'currency',
                      currency: record.currency,
                    }).resolvedOptions().maximumFractionDigits ?? 2;
                  setEditing(record);
                  setDirection(record.direction);
                  setAmount(
                    String(record.amount_minor / 10 ** digits),
                  );
                  setCurrency(record.currency);
                  setDescription(record.description);
                  setCategory(record.category || '');
                  setDialogOpen(true);
                }}
              >
                <Edit3 className="mr-2 h-4 w-4" aria-hidden />
                Edit
              </button>
              <button
                type="button"
                className={destructiveButtonClassName}
                onClick={() => void remove(record)}
                aria-label={`Delete ${record.direction} ${record.description}`}
              >
                <Trash2 className="mr-2 h-4 w-4" aria-hidden />
                Delete
              </button>
            </div>
          </Card>
        ))}
      </ResourceList>
    </>
  );
}

export function GoalsScreen() {
  const resource = useApiResource(
    () => fetchAPI<Goal[]>('/api/v2/goals?limit=100'),
    '',
  );
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [target, setTarget] = useState('');
  const [unit, setUnit] = useState('');
  const [currentValue, setCurrentValue] = useState('0');
  const [editing, setEditing] = useState<Goal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      if (editing) {
        await fetchAPI(`/api/v2/goals/${editing.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            version: editing.version,
            title,
            description: description || null,
            target_value: target || null,
            current_value: currentValue,
            unit: unit || null,
          }),
        });
      } else {
        await fetchAPI('/api/v2/goals', {
          method: 'POST',
          body: JSON.stringify({
            title,
            description: description || null,
            target_value: target || null,
            unit: unit || null,
            idempotency_key: idempotencyKey('goal'),
          }),
        });
      }
      setTitle('');
      setDescription('');
      setTarget('');
      setUnit('');
      setCurrentValue('0');
      setEditing(null);
      setDialogOpen(false);
      await resource.reload();
    } catch (mutationError) {
      setError(
        mutationError instanceof Error
          ? mutationError.message
          : 'Unable to save goal.',
      );
    }
  }

  async function patch(record: Goal, values: Record<string, unknown>) {
    await fetchAPI(`/api/v2/goals/${record.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ version: record.version, ...values }),
    });
    await resource.reload();
  }

  async function remove(record: Goal) {
    if (!window.confirm('Delete this goal permanently?')) return;
    await fetchAPI(`/api/v2/goals/${record.id}`, { method: 'DELETE' });
    await resource.reload();
  }

  return (
    <>
      <ScreenHeading
        title="Goals"
        description="Active targets, progress, and completion status."
        action={<button type="button" className={buttonClassName} onClick={() => { setEditing(null); setTitle(''); setDescription(''); setTarget(''); setUnit(''); setCurrentValue('0'); setDialogOpen(true); }}><Plus className="mr-2 h-4 w-4" aria-hidden />Add</button>}
      />
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
          <DialogHeader><DialogTitle>{editing ? 'Edit goal' : 'Add goal'}</DialogTitle><DialogDescription>Define a target and update its measurable progress.</DialogDescription></DialogHeader>
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        {editing ? (
          <p className="text-sm font-medium sm:col-span-2">Editing goal</p>
        ) : null}
        <div className="sm:col-span-2">
          <FormField label="Goal" htmlFor="goal-title">
            <input
              id="goal-title"
              required
              maxLength={255}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className={inputClassName}
            />
          </FormField>
        </div>
        <div className="sm:col-span-2">
          <FormField label="Description (optional)" htmlFor="goal-description">
            <textarea
              id="goal-description"
              maxLength={10_000}
              rows={3}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className={inputClassName}
            />
          </FormField>
        </div>
        <FormField label="Target (optional)" htmlFor="goal-target">
          <input
            id="goal-target"
            type="number"
            min="0"
            step="0.0001"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            className={inputClassName}
          />
        </FormField>
        <FormField label="Unit (optional)" htmlFor="goal-unit">
          <input
            id="goal-unit"
            maxLength={32}
            value={unit}
            onChange={(event) => setUnit(event.target.value)}
            className={inputClassName}
          />
        </FormField>
        {editing ? (
          <FormField label="Current progress" htmlFor="goal-current">
            <input
              id="goal-current"
              type="number"
              min="0"
              step="0.0001"
              required
              value={currentValue}
              onChange={(event) => setCurrentValue(event.target.value)}
              className={inputClassName}
            />
          </FormField>
        ) : null}
        <div className="sm:col-span-2">
          <MutationError message={error} />
          <button type="submit" className={`${buttonClassName} mt-2`}>
            <Flag className="mr-2 h-4 w-4" aria-hidden />
            {editing ? 'Save goal' : 'Add goal'}
          </button>
          {editing ? (
            <button
              type="button"
              className={`${secondaryButtonClassName} ml-2`}
              onClick={() => {
                setEditing(null);
                setTitle('');
                setDescription('');
                setTarget('');
                setUnit('');
                setCurrentValue('0');
              }}
            >
              Cancel
            </button>
          ) : null}
        </div>
      </form>
        </DialogContent>
      </Dialog>
      <ResourceList resource={resource} emptyLabel="No goals yet.">
        {(resource.data || []).map((record) => (
          <Card key={record.id}>
            <h2 className="break-words font-semibold">{record.title}</h2>
            {record.description ? (
              <p className="mt-1 whitespace-pre-wrap break-words text-sm text-muted-foreground">
                {record.description}
              </p>
            ) : null}
            <p className="mt-1 text-sm text-muted-foreground">
              {formatDecimal(record.current_value)}
              {record.target_value !== null ? ` / ${formatDecimal(record.target_value)}` : ''}
              {record.unit ? ` ${record.unit}` : ''} · {record.status}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                className={secondaryButtonClassName}
                onClick={() => {
                  setEditing(record);
                  setTitle(record.title);
                  setDescription(record.description || '');
                  setTarget(record.target_value || '');
                  setCurrentValue(record.current_value);
                  setUnit(record.unit || '');
                  setDialogOpen(true);
                }}
              >
                <Edit3 className="mr-2 h-4 w-4" aria-hidden />
                Edit
              </button>
              <button
                type="button"
                className={secondaryButtonClassName}
                onClick={() =>
                  void patch(record, {
                    status:
                      record.status === 'paused' ? 'active' : 'paused',
                  })
                }
              >
                {record.status === 'paused' ? 'Resume' : 'Pause'}
              </button>
              <button
                type="button"
                className={secondaryButtonClassName}
                onClick={() =>
                  void patch(record, { status: 'completed' })
                }
              >
                <Check className="mr-2 h-4 w-4" aria-hidden />
                Complete
              </button>
              <button
                type="button"
                className={destructiveButtonClassName}
                onClick={() => void remove(record)}
              >
                <Trash2 className="mr-2 h-4 w-4" aria-hidden />
                Delete
              </button>
            </div>
          </Card>
        ))}
      </ResourceList>
    </>
  );
}

export function NutritionScreen() {
  const [viewMode, setViewMode] = useState<'history' | 'day'>('history');
  const [selectedDate, setSelectedDate] = useState(localDate());
  const resource = useApiResource(async () => {
    const logsPath = viewMode === 'day'
      ? `/api/v2/nutrition?start_date=${selectedDate}&end_date=${selectedDate}&limit=100`
      : '/api/v2/nutrition?limit=100';
    const [logs, summary] = await Promise.all([
      fetchAPI<NutritionLog[]>(logsPath),
      fetchAPI<NutritionSummary>(
        `/api/v2/nutrition/summary?start_date=${selectedDate}&end_date=${selectedDate}`,
      ),
    ]);
    return { logs, summary };
  }, `${viewMode}:${selectedDate}`);
  const [description, setDescription] = useState('');
  const [mealName, setMealName] = useState('');
  const [editingItem, setEditingItem] = useState<{
    log: NutritionLog;
    item: NutritionItem;
  } | null>(null);
  const [manualLog, setManualLog] = useState<NutritionLog | null>(null);
  const [manualName, setManualName] = useState('');
  const [manualCalories, setManualCalories] = useState('');
  const [manualProtein, setManualProtein] = useState('');
  const [quantity, setQuantity] = useState('');
  const [unit, setUnit] = useState('');
  const [calories, setCalories] = useState('');
  const [protein, setProtein] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await fetchAPI('/api/v2/nutrition', {
        method: 'POST',
        body: JSON.stringify({
          original_text: description,
          meal_name: mealName || null,
          timezone: localTimezone,
          idempotency_key: idempotencyKey('food'),
        }),
      });
      setDescription('');
      setMealName('');
      setDialogOpen(false);
      await resource.reload();
    } catch (mutationError) {
      setError(
        mutationError instanceof Error
          ? mutationError.message
          : 'Unable to preview food.',
      );
    }
  }

  async function confirm(log: NutritionLog) {
    await fetchAPI(`/api/v2/nutrition/${log.id}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ version: log.version }),
    });
    await resource.reload();
  }

  async function saveItem(event: FormEvent) {
    event.preventDefault();
    if (!editingItem) return;
    await fetchAPI(
      `/api/v2/nutrition/${editingItem.log.id}/items/${editingItem.item.id}`,
      {
        method: 'PATCH',
        body: JSON.stringify({
          version: editingItem.item.version,
          quantity_value: quantity,
          quantity_unit: unit,
          calories,
          protein_grams: protein,
        }),
      },
    );
    setEditingItem(null);
    await resource.reload();
  }

  async function saveManualNutrition(event: FormEvent) {
    event.preventDefault();
    if (!manualLog) return;
    const assumption = 'Calories and protein entered manually by the user.';
    await fetchAPI(`/api/v2/nutrition/${manualLog.id}/manual`, {
      method: 'POST',
      body: JSON.stringify({
        version: manualLog.version,
        items: [
          {
            original_item_text: manualLog.original_text,
            normalized_name: manualName,
            quantity_value: '1',
            quantity_unit: 'serving',
            portion_description: 'User-entered serving',
            estimated_grams: null,
            calories: manualCalories,
            protein_grams: manualProtein,
            carbohydrate_grams: null,
            fat_grams: null,
            visible_assumptions: [assumption],
            confidence: '1',
          },
        ],
        visible_assumptions: [assumption],
      }),
    });
    setManualLog(null);
    setManualName('');
    setManualCalories('');
    setManualProtein('');
    await resource.reload();
  }

  async function remove(log: NutritionLog) {
    if (!window.confirm('Delete this meal permanently?')) return;
    await fetchAPI(`/api/v2/nutrition/${log.id}`, { method: 'DELETE' });
    await resource.reload();
  }

  function moveDay(delta: number) {
    const current = new Date(`${selectedDate}T12:00:00`);
    current.setDate(current.getDate() + delta);
    setSelectedDate(localDate(current));
  }

  return (
    <>
      <ScreenHeading
        title="Nutrition"
        description="Daily meal analytics with editable AI estimates—not medical advice."
        action={
          <button type="button" className={buttonClassName} onClick={() => setDialogOpen(true)}>
            <Plus className="mr-2 h-4 w-4" aria-hidden />
            Add
          </button>
        }
      />
      <div className="mb-4 rounded-xl border bg-card p-3">
        <div className="grid grid-cols-2 gap-2" role="group" aria-label="Nutrition history range">
          <button
            type="button"
            className={viewMode === 'history' ? buttonClassName : secondaryButtonClassName}
            onClick={() => setViewMode('history')}
          >
            Recent meals
          </button>
          <button
            type="button"
            className={viewMode === 'day' ? buttonClassName : secondaryButtonClassName}
            onClick={() => setViewMode('day')}
          >
            One day
          </button>
        </div>
        {viewMode === 'day' ? (
          <div className="mt-3 flex items-center justify-between">
            <button
              type="button"
              onClick={() => moveDay(-1)}
              className={secondaryButtonClassName}
              aria-label="Previous day"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden />
            </button>
            <time dateTime={selectedDate} className="text-sm font-semibold">
              {selectedDate}
            </time>
            <button
              type="button"
              onClick={() => moveDay(1)}
              className={secondaryButtonClassName}
              aria-label="Next day"
            >
              <ChevronRight className="h-4 w-4" aria-hidden />
            </button>
          </div>
        ) : (
          <p className="mt-3 text-xs text-muted-foreground">
            Showing your latest 100 meals across all dates. Choose One day for daily totals.
          </p>
        )}
      </div>
      {resource.data && viewMode === 'day' ? (
        <div className="mb-4 grid grid-cols-2 gap-3">
          <Metric
            label="Approx. calories"
            value={resource.data.summary.total_calories}
          />
          <Metric
            label="Approx. protein"
            value={`${resource.data.summary.total_protein_grams} g`}
          />
        </div>
      ) : null}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Add a meal</DialogTitle>
            <DialogDescription>
              Describe what you ate naturally. The assistant estimates servings,
              calories, and protein and shows its assumptions for review.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={create} className="space-y-3">
            <FormField label="Food description" htmlFor="food-description">
              <textarea
                id="food-description"
                required
                rows={4}
                maxLength={10_000}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="I had two aloo parathas with curd and a cup of tea"
                className={inputClassName}
              />
            </FormField>
            <FormField label="Meal name (optional)" htmlFor="food-meal">
              <input id="food-meal" maxLength={128} value={mealName} onChange={(event) => setMealName(event.target.value)} className={inputClassName} placeholder="Breakfast" />
            </FormField>
            <MutationError message={error} />
            <button type="submit" className={`${buttonClassName} w-full`}>
              Estimate meal
            </button>
          </form>
        </DialogContent>
      </Dialog>
      {editingItem ? (
        <form
          onSubmit={saveItem}
          className="mb-5 grid gap-3 rounded-xl border-2 border-primary bg-card p-4 sm:grid-cols-2"
          aria-label="Edit food serving"
        >
          <div className="sm:col-span-2">
            <h2 className="font-semibold">
              Edit {editingItem.item.normalized_name}
            </h2>
            <p className="text-xs text-muted-foreground">
              Serving edits require updated calories and protein.
            </p>
          </div>
          {[
            ['food-quantity', 'Quantity', quantity, setQuantity],
            ['food-unit', 'Unit', unit, setUnit],
            ['food-calories', 'Calories', calories, setCalories],
            ['food-protein', 'Protein grams', protein, setProtein],
          ].map(([id, label, value, setter]) => (
            <FormField key={String(id)} label={String(label)} htmlFor={String(id)}>
              <input
                id={String(id)}
                value={String(value)}
                onChange={(event) =>
                  (setter as (next: string) => void)(event.target.value)
                }
                required
                className={inputClassName}
              />
            </FormField>
          ))}
          <div className="flex gap-2 sm:col-span-2">
            <button type="submit" className={buttonClassName}>
              Save serving
            </button>
            <button
              type="button"
              onClick={() => setEditingItem(null)}
              className={secondaryButtonClassName}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}
      {manualLog ? (
        <form
          onSubmit={saveManualNutrition}
          className="mb-5 grid gap-3 rounded-xl border-2 border-primary bg-card p-4 sm:grid-cols-2"
          aria-label="Enter nutrition manually"
        >
          <div className="sm:col-span-2">
            <h2 className="font-semibold">Enter nutrition manually</h2>
            <p className="text-xs text-muted-foreground">
              These values come from you. PR-Agent will not estimate or verify
              them.
            </p>
          </div>
          <FormField label="Food name" htmlFor="manual-food-name">
            <input
              id="manual-food-name"
              required
              maxLength={255}
              value={manualName}
              onChange={(event) => setManualName(event.target.value)}
              className={inputClassName}
            />
          </FormField>
          <FormField label="Calories" htmlFor="manual-food-calories">
            <input
              id="manual-food-calories"
              required
              type="number"
              min="0"
              step="0.01"
              value={manualCalories}
              onChange={(event) => setManualCalories(event.target.value)}
              className={inputClassName}
            />
          </FormField>
          <FormField label="Protein grams" htmlFor="manual-food-protein">
            <input
              id="manual-food-protein"
              required
              type="number"
              min="0"
              step="0.001"
              value={manualProtein}
              onChange={(event) => setManualProtein(event.target.value)}
              className={inputClassName}
            />
          </FormField>
          <div className="flex gap-2 sm:col-span-2">
            <button type="submit" className={buttonClassName}>
              Save manual values
            </button>
            <button
              type="button"
              onClick={() => setManualLog(null)}
              className={secondaryButtonClassName}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}
      <ResourceList
        resource={{ ...resource, data: resource.data?.logs || null }}
        emptyLabel={viewMode === 'day' ? 'No food logs for this day.' : 'No food logs yet.'}
      >
        {(resource.data?.logs || []).map((log) => (
          <Card key={log.id}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="break-words font-semibold">
                  {log.meal_name || 'Meal'}
                </h2>
                <p className="break-words text-sm text-muted-foreground">
                  {log.original_text}
                </p>
                <p className="mt-1 text-xs font-medium text-muted-foreground">
                  {log.user_local_date}
                </p>
              </div>
              <span className="rounded-full bg-muted px-2 py-1 text-xs">
                {log.status}
              </span>
            </div>
            {log.clarification_question ? (
              <div className="mt-3 rounded-lg bg-amber-500/10 p-3 text-sm">
                <p>{log.clarification_question}</p>
                {!log.items.length ? (
                  <button
                    type="button"
                    className={`${secondaryButtonClassName} mt-3`}
                    onClick={() => {
                      setManualLog(log);
                      setManualName(log.meal_name || log.original_text.slice(0, 255));
                      setManualCalories('');
                      setManualProtein('');
                    }}
                  >
                    Enter calories and protein
                  </button>
                ) : null}
              </div>
            ) : null}
            <ul className="mt-3 space-y-2">
              {log.items.map((item) => (
                <li key={item.id} className="rounded-lg bg-muted/60 p-3 text-sm">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="font-medium">{item.normalized_name}</p>
                      <p className="text-muted-foreground">
                        {item.quantity_value} {item.quantity_unit} · ≈{' '}
                        {item.calories} kcal · {item.protein_grams} g protein
                      </p>
                    </div>
                    <button
                      type="button"
                      className={secondaryButtonClassName}
                      onClick={() => {
                        setEditingItem({ log, item });
                        setQuantity(item.quantity_value || '');
                        setUnit(item.quantity_unit || '');
                        setCalories(item.calories);
                        setProtein(item.protein_grams);
                      }}
                      aria-label={`Edit ${item.normalized_name} serving`}
                    >
                      <Edit3 className="h-4 w-4" aria-hidden />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
            {log.visible_assumptions.length ? (
              <details className="mt-3 text-sm">
                <summary className="cursor-pointer font-medium">
                  Visible assumptions
                </summary>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
                  {log.visible_assumptions.map((assumption) => (
                    <li key={assumption}>{assumption}</li>
                  ))}
                </ul>
              </details>
            ) : null}
            <p className="mt-3 text-sm font-medium">
              Approximately {log.total_calories} kcal ·{' '}
              {log.total_protein_grams} g protein
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {log.status === 'draft' && !log.clarification_question ? (
                <button
                  type="button"
                  className={buttonClassName}
                  onClick={() => void confirm(log)}
                >
                  Confirm meal
                </button>
              ) : null}
              <button
                type="button"
                className={destructiveButtonClassName}
                onClick={() => void remove(log)}
              >
                <Trash2 className="mr-2 h-4 w-4" aria-hidden />
                Delete meal
              </button>
            </div>
          </Card>
        ))}
      </ResourceList>
    </>
  );
}

export function SettingsScreen({
  onNavigate,
}: {
  onNavigate?: (screen: ScreenName) => void;
} = {}) {
  const resource = useApiResource(async () => {
    const [settings, nutrition] = await Promise.all([
      fetchAPI<SchedulePreferences>('/api/v2/schedule-preferences'),
      fetchAPI<NutritionPreferences>('/api/v2/nutrition/preferences'),
    ]);
    return { settings, nutrition };
  }, '');
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (resource.loading) return <LoadingState label="Loading settings" />;
  if (resource.error) {
    return <ErrorState message={resource.error} retry={resource.reload} />;
  }
  if (!resource.data) return null;

  return (
    <>
      <ScreenHeading
        title="Settings"
        description="Timezone, nutrition targets, and confirmation preferences."
      />
      <SettingsForm
        key={`${resource.data.nutrition.version}:${resource.data.settings.digest_version}`}
        initial={resource.data}
        onSaved={async (payload) => {
          setSaved(false);
          setError(null);
          try {
            const schedule = await fetchAPI<SchedulePreferences>(
              '/api/v2/schedule-preferences',
              {
                method: 'PATCH',
                body: JSON.stringify({
                  preference_version:
                    resource.data!.settings.preference_version,
                  digest_version: resource.data!.settings.digest_version,
                  timezone: payload.timezone,
                  sunday_digest_enabled: payload.sundayDigestEnabled,
                  sunday_digest_time: payload.sundayDigestTime,
                }),
              },
            );
            await fetchAPI('/api/v2/nutrition/preferences', {
              method: 'PATCH',
              body: JSON.stringify({
                version: schedule.preference_version,
                timezone: payload.timezone,
                calorie_target: payload.calorieTarget || null,
                protein_target_grams: payload.proteinTarget || null,
                default_milk_serving_ml: payload.milkServing,
                measurement_system: payload.measurementSystem,
                nutrition_confirmation_required:
                  payload.confirmationRequired,
              }),
            });
            setSaved(true);
            await resource.reload();
          } catch (mutationError) {
            setError(
              mutationError instanceof Error
                ? mutationError.message
                : 'Unable to save settings.',
            );
          }
        }}
      />
      {saved ? (
        <p className="mt-3 text-sm text-primary" role="status">
          Settings saved.
        </p>
      ) : null}
      <MutationError message={error} />
      <div className="mt-5 rounded-xl border bg-card p-4 shadow-sm">
        <h2 className="font-semibold">Account &amp; data</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Download a private copy or permanently delete your account.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            className={secondaryButtonClassName}
            onClick={() => onNavigate?.('export')}
          >
            <Download className="mr-2 h-4 w-4" aria-hidden />
            Export data
          </button>
          <button
            type="button"
            className={destructiveButtonClassName}
            onClick={() => onNavigate?.('account')}
          >
            <Trash2 className="mr-2 h-4 w-4" aria-hidden />
            Delete account
          </button>
        </div>
      </div>
    </>
  );
}

function SettingsForm({
  initial,
  onSaved,
}: {
  initial: {
    settings: SchedulePreferences;
    nutrition: NutritionPreferences;
  };
  onSaved: (values: {
    timezone: string;
    calorieTarget: string;
    proteinTarget: string;
    milkServing: string;
    measurementSystem: 'metric' | 'imperial';
    confirmationRequired: boolean;
    sundayDigestEnabled: boolean;
    sundayDigestTime: string;
  }) => Promise<void>;
}) {
  const [timezone, setTimezone] = useState(initial.settings.timezone);
  const [calorieTarget, setCalorieTarget] = useState(
    initial.nutrition.calorie_target || '',
  );
  const [proteinTarget, setProteinTarget] = useState(
    initial.nutrition.protein_target_grams || '',
  );
  const [milkServing, setMilkServing] = useState(
    initial.nutrition.default_milk_serving_ml,
  );
  const [measurementSystem, setMeasurementSystem] = useState<
    'metric' | 'imperial'
  >(initial.nutrition.measurement_system);
  const [confirmationRequired, setConfirmationRequired] = useState(
    initial.nutrition.nutrition_confirmation_required,
  );
  const [sundayDigestEnabled, setSundayDigestEnabled] = useState(
    initial.settings.sunday_digest_enabled,
  );
  const [sundayDigestTime, setSundayDigestTime] = useState(
    initial.settings.sunday_digest_time.slice(0, 5),
  );

  return (
    <form
      className="space-y-4 rounded-xl border bg-card p-4"
      onSubmit={(event) => {
        event.preventDefault();
        void onSaved({
          timezone,
          calorieTarget,
          proteinTarget,
          milkServing,
          measurementSystem,
          confirmationRequired,
          sundayDigestEnabled,
          sundayDigestTime,
        });
      }}
    >
      <FormField label="IANA timezone" htmlFor="settings-timezone">
        <input
          id="settings-timezone"
          required
          value={timezone}
          onChange={(event) => setTimezone(event.target.value)}
          className={inputClassName}
        />
      </FormField>
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField
          label="Your calorie target"
          htmlFor="settings-calories"
          hint="Optional. The app never selects a target for you."
        >
          <input
            id="settings-calories"
            type="number"
            min="0"
            step="0.01"
            value={calorieTarget}
            onChange={(event) => setCalorieTarget(event.target.value)}
            className={inputClassName}
          />
        </FormField>
        <FormField
          label="Your protein target (g)"
          htmlFor="settings-protein"
        >
          <input
            id="settings-protein"
            type="number"
            min="0"
            step="0.001"
            value={proteinTarget}
            onChange={(event) => setProteinTarget(event.target.value)}
            className={inputClassName}
          />
        </FormField>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField
          label="Default milk glass (ml)"
          htmlFor="settings-milk"
        >
          <input
            id="settings-milk"
            type="number"
            min="1"
            max="5000"
            value={milkServing}
            onChange={(event) => setMilkServing(event.target.value)}
            className={inputClassName}
          />
        </FormField>
        <FormField label="Measurement system" htmlFor="settings-units">
          <select
            id="settings-units"
            value={measurementSystem}
            onChange={(event) =>
              setMeasurementSystem(
                event.target.value as 'metric' | 'imperial',
              )
            }
            className={inputClassName}
          >
            <option value="metric">Metric</option>
            <option value="imperial">Imperial</option>
          </select>
        </FormField>
      </div>
      <label className="flex min-h-11 items-center gap-3 rounded-lg border p-3 text-sm">
        <input
          type="checkbox"
          checked={confirmationRequired}
          onChange={(event) =>
            setConfirmationRequired(event.target.checked)
          }
          className="h-5 w-5"
        />
        Always require confirmation before nutrition totals count
      </label>
      <div className="rounded-lg border p-3">
        <label className="flex min-h-11 items-center gap-3 text-sm">
          <input
            type="checkbox"
            checked={sundayDigestEnabled}
            onChange={(event) =>
              setSundayDigestEnabled(event.target.checked)
            }
            className="h-5 w-5"
          />
          Send my private Sunday summary
        </label>
        <FormField
          label="Sunday delivery time"
          htmlFor="settings-digest-time"
          hint="Uses the IANA timezone above."
        >
          <input
            id="settings-digest-time"
            type="time"
            required
            disabled={!sundayDigestEnabled}
            value={sundayDigestTime}
            onChange={(event) => setSundayDigestTime(event.target.value)}
            className={inputClassName}
          />
        </FormField>
        {initial.settings.next_digest_at_utc ? (
          <p className="mt-2 text-xs text-muted-foreground">
            Next delivery:{' '}
            {formatDateTime(initial.settings.next_digest_at_utc)}
          </p>
        ) : null}
      </div>
      <button type="submit" className={buttonClassName}>
        Save settings
      </button>
    </form>
  );
}

export function ExportScreen() {
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function downloadExport(format: 'json' | 'csv') {
    setStatus(null);
    setError(null);
    try {
      const response = await fetch(
        `${API_URL}/api/v2/account/export?format=${format}`,
        { credentials: 'include' },
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(
          typeof payload.detail === 'string'
            ? payload.detail
            : 'Unable to download export.',
        );
      }
      const blob = await response.blob();
      const contentDisposition =
        response.headers.get('Content-Disposition') || '';
      const filename =
        contentDisposition.match(/filename="([^"]+)"/)?.[1] ||
        `pr-agent-export.${format === 'csv' ? 'zip' : 'json'}`;
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
      setStatus('Your private export download is ready.');
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to request export.',
      );
    }
  }

  return (
    <>
      <ScreenHeading
        title="Export data"
        description="Request a private export of records owned by your account."
      />
      <Card>
        <p className="text-sm text-muted-foreground">
          Exports are generated server-side and must not be shared through a
          public URL.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            className={buttonClassName}
            onClick={() => void downloadExport('json')}
          >
            <Download className="mr-2 h-4 w-4" aria-hidden />
            Download JSON
          </button>
          <button
            type="button"
            className={secondaryButtonClassName}
            onClick={() => void downloadExport('csv')}
          >
            <Download className="mr-2 h-4 w-4" aria-hidden />
            Download CSV ZIP
          </button>
        </div>
        {status ? (
          <p className="mt-3 text-sm text-primary" role="status">
            {status}
          </p>
        ) : null}
        <MutationError message={error} />
      </Card>
    </>
  );
}

const privateFactLabels: Record<PrivateFactType, string> = {
  aadhaar_last4: 'Aadhaar last 4 digits',
  phone: 'Mobile number',
  bank_account: 'Bank account',
  ifsc: 'IFSC code',
  academic_score: 'Academic score / CGPA',
  other_permitted: 'Other permitted fact',
};

export function VaultScreen() {
  const resource = useApiResource(() =>
    fetchAPI<PrivateFact[]>('/api/v2/private-facts'),
  );
  const [dialogOpen, setDialogOpen] = useState(false);
  const [factType, setFactType] = useState<PrivateFactType>('academic_score');
  const [label, setLabel] = useState('');
  const [value, setValue] = useState('');
  const [notes, setNotes] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [revealed, setRevealed] = useState<RevealedPrivateFact | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const created = await fetchAPI<PrivateFact>('/api/v2/private-facts', {
        method: 'POST',
        body: JSON.stringify({
          fact_type: factType,
          label,
          value,
          notes: notes || null,
          acknowledge_sensitive_storage: acknowledged,
        }),
      });
      resource.setData((current) => [created, ...(current || [])]);
      setDialogOpen(false);
      setLabel('');
      setValue('');
      setNotes('');
      setAcknowledged(false);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to save this private fact.',
      );
    }
  }

  async function reveal(record: PrivateFact) {
    setError(null);
    if (revealed?.id === record.id) {
      setRevealed(null);
      return;
    }
    try {
      setRevealed(
        await fetchAPI<RevealedPrivateFact>(
          `/api/v2/private-facts/${record.id}/reveal`,
          { method: 'POST' },
        ),
      );
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to reveal this private fact.',
      );
    }
  }

  async function remove(record: PrivateFact) {
    if (!window.confirm(`Permanently delete “${record.label}”?`)) return;
    setError(null);
    try {
      await fetchAPI(`/api/v2/private-facts/${record.id}`, { method: 'DELETE' });
      resource.setData((current) =>
        (current || []).filter((item) => item.id !== record.id),
      );
      if (revealed?.id === record.id) setRevealed(null);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to delete this private fact.',
      );
    }
  }

  return (
    <>
      <ScreenHeading
        title="Private facts vault"
        description="Encrypted values available in the Mini App or after an explicit reveal confirmation in private chat."
        action={
          <button type="button" className={buttonClassName} onClick={() => setDialogOpen(true)}>
            <Plus className="mr-2 h-4 w-4" aria-hidden />
            Add
          </button>
        }
      />
      <div className="mb-4 rounded-xl border border-amber-500/40 bg-amber-500/5 p-4 text-sm">
        <p className="font-semibold">Keep authentication secrets elsewhere.</p>
        <p className="mt-1 text-muted-foreground">
          Passwords, OTPs, PINs, CVVs, card numbers, recovery phrases, private
          keys, and full Aadhaar numbers are not accepted. Secret values never
          go to the AI or voice transcription. A value enters Telegram only
          after you confirm a masked match, and that reply is auto-deleted.
        </p>
      </div>
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Add a private fact</DialogTitle>
            <DialogDescription>
              The value and optional note are encrypted before database storage.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={create} className="space-y-3">
            <FormField label="Type" htmlFor="vault-type">
              <select
                id="vault-type"
                value={factType}
                onChange={(event) => setFactType(event.target.value as PrivateFactType)}
                className={inputClassName}
              >
                {Object.entries(privateFactLabels).map(([id, text]) => (
                  <option key={id} value={id}>{text}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Label" htmlFor="vault-label" hint="Example: Semester 4 CGPA or SBI scholarship account.">
              <input id="vault-label" required maxLength={160} value={label} onChange={(event) => setLabel(event.target.value)} className={inputClassName} autoComplete="off" />
            </FormField>
            <FormField label={factType === 'aadhaar_last4' ? 'Last 4 digits only' : 'Value'} htmlFor="vault-value">
              <input id="vault-value" required maxLength={2000} value={value} onChange={(event) => setValue(event.target.value)} className={inputClassName} autoComplete="off" inputMode={factType === 'aadhaar_last4' || factType === 'phone' ? 'numeric' : 'text'} />
            </FormField>
            <FormField label="Private note (optional)" htmlFor="vault-notes">
              <textarea id="vault-notes" maxLength={500} value={notes} onChange={(event) => setNotes(event.target.value)} className={inputClassName} />
            </FormField>
            <label className="flex min-h-11 items-start gap-3 text-sm">
              <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} className="mt-0.5 h-5 w-5" />
              I understand this is sensitive data and I can delete it at any time.
            </label>
            <MutationError message={error} />
            <button type="submit" disabled={!acknowledged} className={`${buttonClassName} w-full`}>
              Save encrypted fact
            </button>
          </form>
        </DialogContent>
      </Dialog>
      <MutationError message={error} />
      <ResourceList resource={resource} emptyLabel="No private facts stored.">
        {(resource.data || []).map((record) => {
          const open = revealed?.id === record.id;
          return (
            <Card key={record.id}>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {privateFactLabels[record.fact_type]}
              </p>
              <h2 className="mt-1 font-semibold">{record.label}</h2>
              <p className="mt-2 break-all font-mono text-sm">
                {open ? revealed.value : record.masked_value}
              </p>
              {open && revealed.notes ? (
                <p className="mt-2 text-sm text-muted-foreground">{revealed.notes}</p>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" className={secondaryButtonClassName} onClick={() => void reveal(record)}>
                  {open ? <EyeOff className="mr-2 h-4 w-4" aria-hidden /> : <Eye className="mr-2 h-4 w-4" aria-hidden />}
                  {open ? 'Hide' : 'Reveal'}
                </button>
                <button type="button" className={destructiveButtonClassName} onClick={() => void remove(record)}>
                  <Trash2 className="mr-2 h-4 w-4" aria-hidden />
                  Delete
                </button>
              </div>
            </Card>
          );
        })}
      </ResourceList>
    </>
  );
}

export function AccountDeletionScreen() {
  const [confirmation, setConfirmation] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function deleteAccount(event: FormEvent) {
    event.preventDefault();
    if (
      confirmation !== 'DELETE MY ACCOUNT' ||
      !acknowledged ||
      !window.confirm(
        'Final confirmation: permanently delete your account and records?',
      )
    ) {
      return;
    }
    try {
      await fetchAPI('/api/v2/account', {
        method: 'DELETE',
        body: JSON.stringify({
          confirmation,
          acknowledge: acknowledged,
        }),
      });
      window.dispatchEvent(new Event('pr-agent:session-expired'));
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to delete account.',
      );
    }
  }

  return (
    <>
      <ScreenHeading
        title="Delete account"
        description="This action is permanent and removes public-v2 records."
      />
      <form
        onSubmit={deleteAccount}
        className="space-y-4 rounded-xl border border-destructive/50 bg-destructive/5 p-4"
      >
        <p className="text-sm">
          Type <strong>DELETE MY ACCOUNT</strong>, check the acknowledgement,
          and approve the final browser confirmation. Download an export first
          from the Export data screen if you want a private copy.
        </p>
        <FormField label="Confirmation phrase" htmlFor="delete-confirmation">
          <input
            id="delete-confirmation"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            autoComplete="off"
            className={inputClassName}
          />
        </FormField>
        <label className="flex min-h-11 items-start gap-3 text-sm">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(event) => setAcknowledged(event.target.checked)}
            className="mt-0.5 h-5 w-5"
          />
          I understand that confirmed deletion cannot be undone.
        </label>
        <MutationError message={error} />
        <button
          type="submit"
          disabled={
            confirmation !== 'DELETE MY ACCOUNT' || !acknowledged
          }
          className={destructiveButtonClassName}
        >
          Delete my account
        </button>
      </form>
    </>
  );
}

function ResourceList<T>({
  resource,
  emptyLabel,
  children,
}: {
  resource: {
    data: T[] | null;
    loading: boolean;
    error: string | null;
    reload: () => Promise<void>;
  };
  emptyLabel: string;
  children: ReactNode;
}) {
  if (resource.loading) return <LoadingState />;
  if (resource.error) {
    return <ErrorState message={resource.error} retry={resource.reload} />;
  }
  if (!resource.data?.length) {
    return (
      <EmptyState title={emptyLabel} description="Use Add to create your first entry." />
    );
  }
  return <div className="space-y-3">{children}</div>;
}

function RecordActions({
  onEdit,
  onDelete,
}: {
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      <button type="button" onClick={onEdit} className={secondaryButtonClassName}>
        <Edit3 className="mr-2 h-4 w-4" aria-hidden />
        Edit
      </button>
      <button
        type="button"
        onClick={onDelete}
        className={destructiveButtonClassName}
      >
        <Trash2 className="mr-2 h-4 w-4" aria-hidden />
        Delete
      </button>
    </div>
  );
}
