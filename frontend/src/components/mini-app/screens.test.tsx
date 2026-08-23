import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  AccountDeletionScreen,
  GoalsScreen,
  MoneyScreen,
  NotesScreen,
  NutritionScreen,
  SettingsScreen,
  VaultScreen,
  WorkLogsScreen,
} from './screens';

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('important Mini App forms', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('creates and edits a work log through authenticated API requests', async () => {
    let records: Array<Record<string, unknown>> = [];
    const requests: Array<{ method: string; body: string | null }> = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, options?: RequestInit) => {
        const method = options?.method || 'GET';
        requests.push({
          method,
          body: typeof options?.body === 'string' ? options.body : null,
        });
        if (method === 'POST') {
          records = [
            {
              id: 1,
              version: 1,
              original_text: 'Initial log',
              cleaned_text: null,
              category: null,
              tags: [],
              logged_at_utc: new Date().toISOString(),
              user_local_date: '2026-07-31',
              timezone: 'UTC',
              capture_source: 'mini_app',
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            },
          ];
          return jsonResponse(records[0], 201);
        }
        if (method === 'PATCH') {
          const payload = JSON.parse(String(options?.body));
          records = [
            {
              ...records[0],
              version: 2,
              original_text: payload.original_text,
            },
          ];
          return jsonResponse(records[0]);
        }
        return jsonResponse(records);
      }),
    );
    const user = userEvent.setup();
    render(<WorkLogsScreen />);

    await screen.findByText('No work logs yet.');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await user.type(
      screen.getByLabelText('What did you complete?'),
      'Initial log',
    );
    await user.click(screen.getByRole('button', { name: 'Add work log' }));
    expect(await screen.findByText('Initial log')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Edit' }));
    const textarea = screen.getByLabelText('What did you complete?');
    await user.clear(textarea);
    await user.type(textarea, 'Edited log');
    await user.click(screen.getByRole('button', { name: 'Save edit' }));
    expect(await screen.findByText('Edited log')).toBeInTheDocument();
    expect(requests.some((request) => request.method === 'POST')).toBe(true);
    expect(
      requests.some(
        (request) =>
          request.method === 'PATCH' &&
          request.body?.includes('"version":1'),
      ),
    ).toBe(true);
  });

  it('saves note titles and tags from the Mini App', async () => {
    let records: Array<Record<string, unknown>> = [];
    let posted: Record<string, unknown> | null = null;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, options?: RequestInit) => {
        if (options?.method === 'POST') {
          const payload = JSON.parse(String(options.body)) as Record<string, unknown>;
          posted = payload;
          records = [{
            id: 1,
            version: 1,
            title: payload.title,
            body: payload.body,
            tags: payload.tags,
            pinned: false,
            capture_source: 'mini_app',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }];
          return jsonResponse(records[0], 201);
        }
        return jsonResponse(records);
      }),
    );
    const user = userEvent.setup();
    render(<NotesScreen />);
    await screen.findByText('No notes yet.');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await user.type(screen.getByLabelText('Title (optional)'), 'Release follow-up');
    await user.type(screen.getByLabelText('Note'), 'Monitor the staging delay.');
    await user.type(screen.getByLabelText('Tags (optional, comma separated)'), 'Staging, Validation');
    await user.click(screen.getByRole('button', { name: 'Add note' }));

    expect(await screen.findByText('Release follow-up')).toBeInTheDocument();
    expect(posted).toMatchObject({ tags: ['staging', 'validation'] });
  });

  it('saves and displays a goal description with readable progress', async () => {
    let records: Array<Record<string, unknown>> = [];
    let posted: Record<string, unknown> | null = null;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, options?: RequestInit) => {
        if (options?.method === 'POST') {
          const payload = JSON.parse(String(options.body)) as Record<string, unknown>;
          posted = payload;
          records = [{
            id: 1,
            version: 1,
            title: payload.title,
            description: payload.description,
            target_value: '20.0000',
            current_value: '0.0000',
            unit: 'scenarios',
            start_date: '2026-08-20',
            due_date: null,
            status: 'active',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }];
          return jsonResponse(records[0], 201);
        }
        return jsonResponse(records);
      }),
    );
    const user = userEvent.setup();
    render(<GoalsScreen />);
    await screen.findByText('No goals yet.');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await user.type(screen.getByLabelText('Goal'), 'Voice coverage');
    await user.type(screen.getByLabelText('Description (optional)'), 'Improve voice-native tracking.');
    await user.type(screen.getByLabelText('Target (optional)'), '20');
    await user.type(screen.getByLabelText('Unit (optional)'), 'scenarios');
    await user.click(screen.getByRole('button', { name: 'Add goal' }));

    expect(await screen.findByText('Improve voice-native tracking.')).toBeInTheDocument();
    expect(screen.getByText(/0 \/ 20 scenarios/)).toBeInTheDocument();
    expect(posted).toMatchObject({ description: 'Improve voice-native tracking.' });
  });

  it('shows historical transactions first and makes categories visible', async () => {
    const requestedUrls: string[] = [];
    const timestamp = new Date().toISOString();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (urlValue: string) => {
        const url = String(urlValue);
        requestedUrls.push(url);
        if (url.includes('/ledger/summary')) return jsonResponse([]);
        return jsonResponse([
          {
            id: 7,
            version: 1,
            direction: 'expense',
            amount_minor: 29900,
            currency: 'INR',
            category: 'Bills',
            description: 'Mobile data recharge',
            transaction_at_utc: timestamp,
            user_local_date: '2026-07-05',
            timezone: 'Asia/Kolkata',
            capture_source: 'telegram_text',
            created_at: timestamp,
            updated_at: timestamp,
          },
          {
            id: 8,
            version: 1,
            direction: 'income',
            amount_minor: 500000,
            currency: 'INR',
            category: 'Freelance',
            description: 'Client payment',
            transaction_at_utc: timestamp,
            user_local_date: '2026-07-06',
            timezone: 'Asia/Kolkata',
            capture_source: 'telegram_text',
            created_at: timestamp,
            updated_at: timestamp,
          },
        ]);
      }),
    );
    const user = userEvent.setup();
    render(<MoneyScreen />);

    expect(await screen.findByText('Mobile data recharge')).toBeInTheDocument();
    expect(screen.getByText('Client payment')).toBeInTheDocument();
    expect(screen.getByText(/Expense · 2026-07-05/)).toHaveClass('text-red-700');
    expect(screen.getByText(/Income · 2026-07-06/)).toHaveClass('text-emerald-700');
    expect(screen.getByText('Bills')).toBeInTheDocument();
    expect(requestedUrls.some((url) => url.endsWith('/api/v2/ledger?limit=100'))).toBe(true);

    await user.click(screen.getByRole('button', { name: 'One month' }));
    await waitFor(() =>
      expect(requestedUrls.some((url) => url.includes('start_date='))).toBe(true),
    );
  });

  it('filters work and notes by day, week, and month ranges', async () => {
    const requestedUrls: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (urlValue: string) => {
        requestedUrls.push(String(urlValue));
        return jsonResponse([]);
      }),
    );
    const user = userEvent.setup();
    const work = render(<WorkLogsScreen />);
    await screen.findByText('No work logs yet.');
    await user.click(screen.getByRole('button', { name: 'Week' }));
    await waitFor(() =>
      expect(
        requestedUrls.some(
          (url) =>
            url.includes('/api/v2/work-logs?start_date=') &&
            url.includes('&end_date='),
        ),
      ).toBe(true),
    );
    work.unmount();

    render(<NotesScreen />);
    await screen.findByText('No notes yet.');
    await user.click(screen.getByRole('button', { name: 'Month' }));
    await waitFor(() =>
      expect(
        requestedUrls.some(
          (url) =>
            url.includes('/api/v2/notes?start_date=') &&
            url.includes('&end_date=') &&
            url.includes('&timezone='),
        ),
      ).toBe(true),
    );
  });

  it('shows a previous-day meal in recent history instead of appearing empty', async () => {
    const timestamp = new Date().toISOString();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (urlValue: string) => {
        const url = String(urlValue);
        if (url.includes('/nutrition/summary')) {
          return jsonResponse({
            start_date: '2026-08-22',
            end_date: '2026-08-22',
            confirmed_meals: 0,
            unestimated_meals: 0,
            total_calories: '0',
            total_protein_grams: '0',
            total_carbohydrate_grams: '0',
            total_fat_grams: '0',
            average_daily_calories: '0',
            average_daily_protein_grams: '0',
            calorie_target: null,
            protein_target_grams: null,
          });
        }
        return jsonResponse([
          {
            id: 8,
            version: 2,
            meal_name: 'Dinner',
            logged_at_utc: timestamp,
            user_local_date: '2026-08-21',
            timezone: 'Asia/Kolkata',
            original_text: 'Two rotis and dal',
            status: 'confirmed',
            total_calories: '430',
            total_protein_grams: '18',
            total_carbohydrate_grams: '60',
            total_fat_grams: '10',
            estimation_source: 'reference:test',
            overall_confidence: '0.8',
            visible_assumptions: [],
            provider_metadata: {},
            clarification_question: null,
            confirmed_by_user: true,
            user_modified: false,
            items: [],
            created_at: timestamp,
            updated_at: timestamp,
          },
        ]);
      }),
    );

    render(<NutritionScreen />);

    expect(await screen.findByText('Two rotis and dal')).toBeInTheDocument();
    expect(screen.getByText('2026-08-21')).toBeInTheDocument();
    expect(screen.getByText(/latest 100 meals across all dates/i)).toBeInTheDocument();
  });

  it('requires typed, checked, and final confirmation for account deletion', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, { status: 204 }),
    );
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    render(<AccountDeletionScreen />);

    const deleteButton = screen.getByRole('button', {
      name: 'Delete my account',
    });
    expect(deleteButton).toBeDisabled();
    await user.type(
      screen.getByLabelText('Confirmation phrase'),
      'DELETE MY ACCOUNT',
    );
    await user.click(
      screen.getByLabelText(
        'I understand that confirmed deletion cannot be undone.',
      ),
    );
    expect(deleteButton).toBeEnabled();
    await user.click(deleteButton);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/v2/account'),
        expect.objectContaining({ method: 'DELETE' }),
      ),
    );
  });

  it('updates shared schedule and nutrition preferences without a version race', async () => {
    const patchRequests: Array<{ url: string; body: Record<string, unknown> }> =
      [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (urlValue: string, options?: RequestInit) => {
        const url = String(urlValue);
        const method = options?.method || 'GET';
        if (method === 'PATCH') {
          const body = JSON.parse(String(options?.body)) as Record<
            string,
            unknown
          >;
          patchRequests.push({ url, body });
          if (url.endsWith('/api/v2/schedule-preferences')) {
            return jsonResponse({
              preference_version: 2,
              digest_version: 2,
              timezone: 'UTC',
              sunday_digest_enabled: true,
              sunday_digest_time: '20:00:00',
              next_digest_at_utc: new Date().toISOString(),
            });
          }
          return jsonResponse({
            owner_id: 1,
            version: 3,
            timezone: 'UTC',
            calorie_target: null,
            protein_target_grams: null,
            carbohydrate_target_grams: null,
            fat_target_grams: null,
            default_milk_serving_ml: '250.00',
            measurement_system: 'metric',
            nutrition_confirmation_required: true,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          });
        }
        if (url.endsWith('/api/v2/schedule-preferences')) {
          return jsonResponse({
            preference_version: 1,
            digest_version: 1,
            timezone: 'UTC',
            sunday_digest_enabled: false,
            sunday_digest_time: '20:00:00',
            next_digest_at_utc: null,
          });
        }
        return jsonResponse({
          owner_id: 1,
          version: 1,
          timezone: 'UTC',
          calorie_target: null,
          protein_target_grams: null,
          carbohydrate_target_grams: null,
          fat_target_grams: null,
          default_milk_serving_ml: '250.00',
          measurement_system: 'metric',
          nutrition_confirmation_required: true,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        });
      }),
    );
    const user = userEvent.setup();
    render(<SettingsScreen />);
    await user.click(await screen.findByText('Send my private Sunday summary'));
    await user.click(screen.getByRole('button', { name: 'Save settings' }));

    await waitFor(() => expect(patchRequests).toHaveLength(2));
    expect(patchRequests[0].url).toContain('/schedule-preferences');
    expect(patchRequests[1].url).toContain('/nutrition/preferences');
    expect(patchRequests[1].body.version).toBe(2);
  });

  it('keeps vault lists masked and requires acknowledgement before saving', async () => {
    const requests: Array<{ url: string; method: string; body: string | null }> = [];
    const timestamp = new Date().toISOString();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (urlValue: string, options?: RequestInit) => {
        const url = String(urlValue);
        const method = options?.method || 'GET';
        const body = typeof options?.body === 'string' ? options.body : null;
        requests.push({ url, method, body });
        if (url.endsWith('/reveal')) {
          return jsonResponse({
            id: 1,
            record_uuid: '11111111-1111-1111-1111-111111111111',
            fact_type: 'academic_score',
            label: 'Semester 4 CGPA',
            masked_value: 'Stored score',
            value: '8.72',
            notes: null,
            version: 1,
            created_at: timestamp,
            updated_at: timestamp,
          });
        }
        if (method === 'POST') {
          return jsonResponse(
            {
              id: 1,
              record_uuid: '11111111-1111-1111-1111-111111111111',
              fact_type: 'academic_score',
              label: 'Semester 4 CGPA',
              masked_value: 'Stored score',
              version: 1,
              created_at: timestamp,
              updated_at: timestamp,
            },
            201,
          );
        }
        return jsonResponse([]);
      }),
    );
    const user = userEvent.setup();
    render(<VaultScreen />);
    await screen.findByText('No private facts stored.');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await user.type(screen.getByLabelText('Label'), 'Semester 4 CGPA');
    await user.type(screen.getByLabelText('Value'), '8.72');
    const save = screen.getByRole('button', { name: 'Save encrypted fact' });
    expect(save).toBeDisabled();
    await user.click(
      screen.getByLabelText(
        'I understand this is sensitive data and I can delete it at any time.',
      ),
    );
    await user.click(save);
    expect(await screen.findByText('Stored score')).toBeInTheDocument();
    expect(screen.queryByText('8.72')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Reveal' }));
    expect(await screen.findByText('8.72')).toBeInTheDocument();
    expect(
      requests.some(
        (request) =>
          request.method === 'POST' &&
          request.body?.includes('"acknowledge_sensitive_storage":true'),
      ),
    ).toBe(true);
  });
});
