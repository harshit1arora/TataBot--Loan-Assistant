import { Toaster as Sonner, type ToasterProps } from "sonner";

/**
 * Toast surface.
 *
 * The shadcn wrapper depended on next-themes, which does not belong in a Vite SPA.
 * The app is light-mode only, so the theme is fixed rather than guessed.
 */
const Toaster = (props: ToasterProps) => (
  <Sonner theme="light" className="toaster group" toastOptions={{ duration: 4000 }} {...props} />
);

export { Toaster };
