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
import { fetchAPI, setCsrfToken } from '@/lib/utils';

interface TelegramWebApp {
  initData: string;
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

    try {
      const webApp = window.Telegram?.WebApp;
      const initData = webApp?.initData;
      if (!initData) {
        throw new Error('Open this dashboard from the bot in Telegram.');
      }

      webApp.ready();
      webApp.expand();

      const result = await fetchAPI<TelegramAuthResponse>(
        '/api/auth/telegram',
        {
          method: 'POST',
          body: JSON.stringify({ init_data: initData }),
        },
      );
      setCsrfToken(result.csrf_token);
      setUser(result.user);
    } catch (authError) {
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

  const logout = useCallback(async () => {
    try {
      await fetchAPI('/api/auth/logout', { method: 'POST' });
    } finally {
      setCsrfToken(null);
      setUser(null);
      setError('Open the dashboard from the bot to sign in again.');
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
