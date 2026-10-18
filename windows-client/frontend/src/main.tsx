import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { installDevMock } from "./devmock";
import { ToastProvider } from "./ui";

// no build de produção o Vite remove isto (e o devmock) por completo
if (import.meta.env.DEV) installDevMock();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </StrictMode>,
);
