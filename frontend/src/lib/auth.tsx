'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { fetchAPI, setAccessToken, setCsrfToken } from '@/lib/utils';

interface TelegramWebApp {
  initData: string;
  colorScheme?: 'light' | 'dark';
  ready: () => void;
  expand: () => void;
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}

export interface AuthenticatedUser {
  id: number;
  telegram_id: number;
  username?: string | null;
  first_name?: string | null;
  streak?: number;
  total_entries?: number;
}

interface TelegramAuthResponse {
  success: boolean;
  access_token: string;
  csrf_token: string;
  expires_in: number;
  user: AuthenticatedUser;
}

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  user: AuthenticatedUser | null;
  retry: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const authenticate = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    setAccessToken(null);

    try {
      const webApp = window.Telegram?.WebApp;
      const initData = webApp?.initData;
      if (!initData) {
        throw new Error('Open this Mini App from the bot in Telegram.');
      }

      webApp.ready();
      webApp.expand();
      if (webApp.colorScheme) {
        document.documentElement.classList.toggle(
          'dark',
          webApp.colorScheme === 'dark',
        );
      }

      const result = await fetchAPI<TelegramAuthResponse>(
        '/api/auth/telegram',
        {
          method: 'POST',
          body: JSON.stringify({ init_data: initData }),
        },
      );
      setAccessToken(result.access_token);
      setCsrfToken(result.csrf_token);
      setUser(result.user);
    } catch (authError) {
      setAccessToken(null);
      setCsrfToken(null);
      setUser(null);
      setError(
        authError instanceof Error
          ? authError.message
          : 'Telegram authentication failed.',
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void authenticate();
  }, [authenticate]);

  useEffect(() => {
    const handleSessionExpiry = () => {
      setAccessToken(null);
      setCsrfToken(null);
      setUser(null);
      setError('Your session expired. Reopen or retry the Mini App.');
    };
    window.addEventListener('pr-agent:session-expired', handleSessionExpiry);
    return () => {
      window.removeEventListener(
        'pr-agent:session-expired',
        handleSessionExpiry,
      );
    };
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetchAPI('/api/auth/logout', { method: 'POST' });
    } finally {
      setAccessToken(null);
      setCsrfToken(null);
      setUser(null);
      setError('Open the Mini App from the bot to sign in again.');
    }
  }, []);

  const value = useMemo<AuthContextType>(
    () => ({
      isAuthenticated: user !== null,
      isLoading,
      error,
      user,
      retry: authenticate,
      logout,
    }),
    [authenticate, error, isLoading, logout, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
