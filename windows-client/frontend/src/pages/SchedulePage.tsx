import clsx from "clsx";
import { useState } from "react";
import { AdminBanner } from "../AdminBanner";
import { backend } from "../backend";
import { errText } from "../format";
import type { Schedule, UIState } from "../types";
import { Button, Card, Field, useToast } from "../ui";

const DAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];

export default function SchedulePage({ state }: { state: UIState }) {
  const toast = useToast();
  const [s, setS] = useState<Schedule>({ ...state.schedule, days: state.schedule.days ?? [] });
  const [saving, setSaving] = useState(false);
  const days = s.days ?? [];
  const locked = !state.admin;

  async function save() {
    setSaving(true);
    try {
      await backend.saveSchedule(s);
      toast("ok", "Agendamento salvo");
    } catch (e) {
      toast("err", errText(e));
    } finally {
      setSaving(false);
    }
  }

  const modeBtn = (mode: Schedule["mode"], label: string) => (
    <button
      type="button"
      disabled={locked}
      onClick={() => setS({ ...s, mode })}
      className={clsx(
        "rounded-lg border px-3 py-2 text-sm font-medium disabled:opacity-60",
        s.mode === mode
          ? "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300"
          : "border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800",
      )}
    >
      {label}
    </button>
  );

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <AdminBanner state={state} />
      <Card className="space-y-4 p-5">
        <div className="flex flex-wrap gap-2">
          {modeBtn("daily", "Em horário fixo")}
          {modeBtn("interval", "A cada N horas")}
          {modeBtn("manual", "Só manual")}
        </div>

        {s.mode === "daily" && (
          <div className="space-y-3">
            <Field label="Horário" hint="O serviço roda mesmo sem ninguém logado, mas o computador precisa estar ligado.">
              <input
                type="time"
                className="input max-w-[9rem]"
                value={s.time}
                disabled={locked}
                onChange={(e) => setS({ ...s, time: e.target.value })}
              />
            </Field>
            <div>
              <span className="label">Dias</span>
              <div className="flex flex-wrap gap-1.5">
                {DAYS.map((d, i) => {
                  const on = days.length === 0 || days.includes(i);
                  return (
                    <button
                      key={d}
                      type="button"
                      disabled={locked}
                      onClick={() => {
                        const cur = days.length === 0 ? [0, 1, 2, 3, 4, 5, 6] : days;
                        const next = cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i].sort();
                        setS({ ...s, days: next.length === 7 ? [] : next });
                      }}
                      className={clsx(
                        "w-12 rounded-lg border py-1.5 text-sm disabled:opacity-60",
                        on
                          ? "border-brand-500 bg-brand-600 text-white dark:bg-brand-500"
                          : "border-slate-300 text-slate-500 dark:border-slate-700 dark:text-slate-400",
                      )}
                    >
                      {d}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {s.mode === "interval" && (
          <Field label="Intervalo (horas)" hint="Conta a partir do último backup. De 1 a 168 (uma semana).">
            <input
              type="number"
              min={1}
              max={168}
              className="input max-w-[9rem]"
              value={s.interval_hours || 24}
              disabled={locked}
              onChange={(e) => setS({ ...s, interval_hours: Number(e.target.value) })}
            />
          </Field>
        )}

        {s.mode !== "manual" && (
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={s.catch_up}
              disabled={locked}
              onChange={(e) => setS({ ...s, catch_up: e.target.checked })}
            />
            <span>
              Se o computador estiver desligado no horário, fazer o backup <b>assim que ele ligar</b>.
            </span>
          </label>
        )}

        <div className="flex justify-end">
          <Button onClick={save} loading={saving} disabled={locked}>
            Salvar agendamento
          </Button>
        </div>
      </Card>

      <Card className="space-y-2">
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={state.use_vss}
            disabled={locked}
            onChange={async (e) => {
              try {
                await backend.setVSS(e.target.checked);
              } catch (err) {
                toast("err", errText(err));
              }
            }}
          />
          <span>
            <b>Cópia de sombra (VSS)</b> — recomendado: antes de cada backup o Windows tira uma “foto” dos discos e os arquivos
            são lidos dela. Arquivos abertos e travados (Outlook .pst, planilhas e bancos em uso) entram num estado consistente.
            A cópia é apagada no fim do backup.
          </span>
        </label>
        <p className="text-xs text-slate-400 dark:text-slate-500">
          Vale para discos locais NTFS. Pendrives, HDs externos FAT/exFAT e pastas de rede são lidos direto (arquivos em uso podem
          ser pulados). Se a cópia falhar, o backup continua lendo ao vivo e o histórico mostra um aviso.
        </p>
      </Card>
    </div>
  );
}
