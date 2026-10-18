// Ponte com o Go: as funções em ../wailsjs são geradas pelo `wails build` a partir
// dos métodos exportados de App (app.go). Aqui só damos os tipos de types.ts.
import * as App from "../wailsjs/go/main/App";
import { config } from "../wailsjs/go/models";
import { EventsOn } from "../wailsjs/runtime/runtime";
import type { ConnectInfo, Progress, Schedule, UIState } from "./types";

export const backend = {
  getState: () => App.GetState() as unknown as Promise<UIState>,
  testConnection: (url: string, token: string) => App.TestConnection(url, token) as unknown as Promise<ConnectInfo>,
  confirmConnection: () => App.ConfirmConnection(),
  disconnect: () => App.Disconnect(),
  chooseFolder: () => App.ChooseFolder(),
  chooseFiles: () => App.ChooseFiles(),
  removeItem: (path: string) => App.RemoveItem(path),
  saveExcludes: (lines: string[]) => App.SaveExcludes(lines),
  chooseWorkDir: () => App.ChooseWorkDir(),
  saveSchedule: (s: Schedule) => App.SaveSchedule(config.Schedule.createFrom(s)),
  setStartWithWindows: (on: boolean) => App.SetStartWithWindows(on),
  openLog: () => App.OpenLog(),
  openConfigDir: () => App.OpenConfigDir(),
  runNow: () => App.RunNow(),
  cancel: () => App.Cancel(),
  quit: () => App.Quit(),
};

export function onState(cb: (s: UIState) => void): () => void {
  return EventsOn("state", (s: UIState) => cb(s));
}

export function onProgress(cb: (p: Progress) => void): () => void {
  return EventsOn("progress", (p: Progress) => cb(p));
}
