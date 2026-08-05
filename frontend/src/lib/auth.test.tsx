import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from './auth';
import { fetchAPI, setAccessToken } from './utils';

function AuthState() {
  const { isAuthenticated, error, user, logout } = useAuth();
  return (
    <div>
      <span>{isAuthenticated ? user?.first_name : error || 'loading'}</span>
      <button type="button" onClick={() => void logout()}>
        Log out
      </button>
    </div>
  );
}

function setTelegram(initData: string) {
  window.Telegram = {
    WebApp: {
      initData,
      colorScheme: 'dark',
      ready: vi.fn(),
      expand: vi.fn(),
    },
  };
}

describe('Telegram Mini App authentication', () => {
  afterEach(() => {
    setAccessToken(null);
    vi.unstubAllGlobals();
    delete window.Telegram;
    document.documentElement.classList.remove('dark');
  });

  it('submits validated initData and enters the authenticated state', async () => {
    setTelegram('signed-init-data');
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            success: true,
            access_token: 'session-token',
            csrf_token: 'csrf-token',
            expires_in: 900,
            user: {
              id: 1,
              telegram_id: 101,
              first_name: 'Alice',
            },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    render(
      <AuthProvider>
        <AuthState />
      </AuthProvider>,
    );

    expect(await screen.findByText('Alice')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/auth/telegram'),
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
      }),
    );
    expect(document.documentElement).toHaveClass('dark');

    await fetchAPI('/api/v2/notes?limit=1');
    const request = fetchMock.mock.calls.at(-1)?.[1] as RequestInit;
    expect(new Headers(request.headers).get('Authorization')).toBe(
      'Bearer session-token',
    );
  });

  it('shows a safe error for invalid authentication', async () => {
    setTelegram('forged-init-data');
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Invalid Telegram signature' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    render(
      <AuthProvider>
        <AuthState />
      </AuthProvider>,
    );

    expect(
      await screen.findByText('Invalid Telegram signature'),
    ).toBeInTheDocument();
  });

  it('clears the session on expiry and logout', async () => {
    setTelegram('signed-init-data');
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            success: true,
            access_token: 'session-token',
            csrf_token: 'csrf-token',
            expires_in: 900,
            user: {
              id: 1,
              telegram_id: 101,
              first_name: 'Alice',
            },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValue(
        new Response(JSON.stringify({ success: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    render(
      <AuthProvider>
        <AuthState />
      </AuthProvider>,
    );
    await screen.findByText('Alice');
    await user.click(screen.getByRole('button', { name: 'Log out' }));
    await waitFor(() =>
      expect(
        screen.getByText('Open the Mini App from the bot to sign in again.'),
      ).toBeInTheDocument(),
    );

    act(() => {
      window.dispatchEvent(new Event('pr-agent:session-expired'));
    });
    expect(
      await screen.findByText(
        'Your session expired. Reopen or retry the Mini App.',
      ),
    ).toBeInTheDocument();
  });
});
