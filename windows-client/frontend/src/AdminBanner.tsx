import { backend } from "./backend";
import { errText } from "./format";
import type { UIState } from "./types";
import { Button, Note, useToast } from "./ui";

/** Configuração só com o processo elevado: fora dele, mostra o botão do UAC. */
export function AdminBanner({ state }: { state: UIState }) {
  const toast = useToast();
  if (state.admin || !state.service_ok) return null;
  return (
    <Note tone="warn">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>Para alterar a configuração é preciso abrir como administrador.</span>
        <Button
          variant="ghost"
          onClick={() => backend.elevate().catch((e) => toast("err", errText(e)))}
        >
          Abrir como administrador
        </Button>
      </div>
    </Note>
  );
}
