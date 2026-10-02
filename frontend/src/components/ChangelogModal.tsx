import { CHANGELOG } from "../lib/changelog";
import { Modal } from "./ui";

export function ChangelogModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onClose={onClose} title="Notas de versão" wide>
      <div className="space-y-5">
        {CHANGELOG.map((entry) => (
          <div key={entry.version}>
            <div className="mb-1 flex items-baseline gap-2">
              <span className="font-bold">v{entry.version}</span>
              <span className="text-xs text-slate-400 dark:text-slate-500">{entry.date}</span>
            </div>
            <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600 dark:text-slate-300">
              {entry.changes.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Modal>
  );
}
