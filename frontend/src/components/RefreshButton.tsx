import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { Button } from "./ui";

/**
 * Botão "Atualizar" para telas com listas em cache (react-query).
 * `keys` são os primeiros segmentos das queryKeys da página; invalida (e
 * refaz) todas elas e mostra o spinner enquanto alguma estiver buscando.
 */
export function RefreshButton({ keys, className }: { keys: string[]; className?: string }) {
  const qc = useQueryClient();
  const fetching =
    useIsFetching({ predicate: (q) => keys.includes(String(q.queryKey[0])) }) > 0;

  return (
    <Button
      variant="ghost"
      className={className}
      loading={fetching}
      onClick={() => keys.forEach((k) => qc.invalidateQueries({ queryKey: [k] }))}
      title="Recarregar os dados desta tela"
    >
      {!fetching && (
        <svg
          className="h-4 w-4"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
          <path d="M21 3v5h-5" />
          <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
          <path d="M3 21v-5h5" />
        </svg>
      )}
      Atualizar
    </Button>
  );
}
