'use client';

import { AlertCircle, Inbox, LoaderCircle, RefreshCw } from 'lucide-react';
import type { ReactNode } from 'react';

export function ScreenHeading({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-5 flex items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}

export function LoadingState({ label = 'Loading' }: { label?: string }) {
  return (
    <div
      className="flex min-h-40 items-center justify-center gap-2 rounded-xl border bg-card text-sm text-muted-foreground"
      role="status"
    >
      <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center rounded-xl border border-dashed bg-card p-5 text-center">
      <Inbox className="mb-2 h-6 w-6 text-muted-foreground" aria-hidden />
      <h2 className="font-semibold">{title}</h2>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">
        {description}
      </p>
    </div>
  );
}

export function ErrorState({
  message,
  retry,
}: {
  message: string;
  retry: () => Promise<void>;
}) {
  return (
    <div
      className="rounded-xl border border-destructive/40 bg-destructive/5 p-4"
      role="alert"
    >
      <div className="flex items-start gap-2">
        <AlertCircle
          className="mt-0.5 h-5 w-5 text-destructive"
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <p className="font-medium">This screen could not be loaded</p>
          <p className="mt-1 break-words text-sm text-muted-foreground">
            {message}
          </p>
          <button
            type="button"
            onClick={() => void retry()}
            className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-lg border bg-background px-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <RefreshCw className="h-4 w-4" aria-hidden />
            Retry
          </button>
        </div>
      </div>
    </div>
  );
}

export function FormField({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint ? (
        <p id={`${htmlFor}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export const inputClassName =
  'min-h-11 w-full rounded-lg border bg-background px-3 py-2 text-base outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60';

export const buttonClassName =
  'inline-flex min-h-11 items-center justify-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60';

export const secondaryButtonClassName =
  'inline-flex min-h-11 items-center justify-center rounded-lg border bg-background px-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60';

export const destructiveButtonClassName =
  'inline-flex min-h-11 items-center justify-center rounded-lg bg-destructive px-3 text-sm font-semibold text-destructive-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60';
