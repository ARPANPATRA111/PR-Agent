'use client';

import { createContext, useContext, useState, useEffect, ReactNode } from 'react';

interface AuthContextType {
  isAuthenticated: boolean;
  login: (password: string) => boolean;
  logout: () => void;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const AUTH_KEY = 'weekly_agent_auth';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const auth = localStorage.getItem(AUTH_KEY);
    if (auth === 'true') {
      setIsAuthenticated(true);
    }
    setIsLoading(false);
  }, []);

  const login = (password: string): boolean => {
    const dashboardPassword = process.env.NEXT_PUBLIC_DASHBOARD_PASSWORD;
    
    if (!dashboardPassword) {
      console.warn('No DASHBOARD_PASSWORD set - allowing access');
      setIsAuthenticated(true);
      localStorage.setItem(AUTH_KEY, 'true');
      return true;
    }
    
    if (password === dashboardPassword) {
      setIsAuthenticated(true);
      localStorage.setItem(AUTH_KEY, 'true');
      return true;
    }
    
    return false;
  };

  const logout = () => {
    setIsAuthenticated(false);
    localStorage.removeItem(AUTH_KEY);
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, login, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
