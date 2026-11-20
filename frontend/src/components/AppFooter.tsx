import { useState } from "react";
import { APP_VERSION } from "../lib/changelog";
import { ChangelogModal } from "./ChangelogModal";

/** Rodapé com copyright e link para as notas de versão. */
export function AppFooter({ className = "" }: { className?: string }) {
  const [showChangelog, setShowChangelog] = useState(false);
  return (
    <div className={`text-xs leading-relaxed text-slate-400 dark:text-slate-500 ${className}`}>
      <div>
        © {new Date().getFullYear()} H2NODE Backup{" "}
        <button
          type="button"
          onClick={() => setShowChangelog(true)}
          className="font-medium text-brand-600 hover:underline dark:text-brand-400"
        >
          v{APP_VERSION}
        </button>
      </div>
      <ChangelogModal open={showChangelog} onClose={() => setShowChangelog(false)} />
    </div>
  );
}
