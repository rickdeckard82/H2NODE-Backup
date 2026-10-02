import { useAuth } from "./auth";
import { fmtDate } from "./format";

export const DEFAULT_TZ = "America/Sao_Paulo";

/** Fusos comuns no Brasil + UTC, para o seletor no cadastro do usuário. */
export const TIMEZONES = [
  "America/Sao_Paulo",
  "America/Bahia",
  "America/Fortaleza",
  "America/Belem",
  "America/Recife",
  "America/Araguaina",
  "America/Campo_Grande",
  "America/Cuiaba",
  "America/Manaus",
  "America/Porto_Velho",
  "America/Boa_Vista",
  "America/Rio_Branco",
  "America/Noronha",
  "UTC",
];

/** Formatador de data já preso ao fuso do operador logado. */
export function useFmtDate(): (v: string | null | undefined) => string {
  const { user } = useAuth();
  const tz = user?.timezone || DEFAULT_TZ;
  return (v) => fmtDate(v, tz);
}
