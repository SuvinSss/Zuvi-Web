import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";

export function Alert({
  kind = "error",
  children,
}: {
  kind?: "error" | "warn" | "info";
  children: ReactNode;
}) {
  return (
    <div className={`alert ${kind}`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="muted" role="status" aria-live="polite">
      {label}
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted">{children}</p>;
}

export function ErrorRetry({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Alert>
      <div className="row">
        <span>{message}</span>
        {onRetry && (
          <button type="button" className="btn secondary" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </Alert>
  );
}

export function Button(
  props: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "link" },
) {
  const { variant = "primary", className = "", ...rest } = props;
  const cls = variant === "primary" ? "btn" : `btn ${variant}`;
  return <button type="button" className={`${cls} ${className}`.trim()} {...rest} />;
}

export function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string | undefined;
  children: (ids: { id: string; describedBy: string | undefined }) => ReactNode;
}) {
  const id = useId();
  const errId = `${id}-err`;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children({ id, describedBy: error ? errId : undefined })}
      {error && (
        <span id={errId} className="field-error">
          {error}
        </span>
      )}
    </div>
  );
}

export function Dialog({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [onClose]);
  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={ref}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 id={titleId}>{title}</h2>
          <Button variant="link" onClick={onClose} aria-label="Close">
            Close
          </Button>
        </div>
        {children}
      </div>
    </div>
  );
}
