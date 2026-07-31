import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  AccountDeletionScreen,
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
});
