/**
 * Ondas animadas decorativas, posicionadas no fundo do elemento pai (que precisa
 * ser `relative`). `screen` = tela de login (três camadas altas); `bar` = faixa
 * baixa para o cabeçalho e o rodapé do app.
 */
export function Waves({ variant }: { variant: "screen" | "bar" }) {
  if (variant === "screen") {
    return (
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        <svg
          className="animate-wave-drift absolute bottom-0 left-0 h-56 w-[200%] text-brand-600/[0.10] dark:text-brand-400/[0.12]"
          style={{ animationDuration: "26s" }}
          viewBox="0 0 2880 320"
          preserveAspectRatio="none"
          fill="currentColor"
        >
          <path d="M0,160 C240,220 480,100 720,160 C960,220 1200,100 1440,160 C1680,220 1920,100 2160,160 C2400,220 2640,100 2880,160 L2880,320 L0,320 Z" />
        </svg>
        <svg
          className="animate-wave-drift absolute bottom-0 left-0 h-40 w-[200%] text-brand-500/[0.08] dark:text-brand-300/[0.08]"
          style={{ animationDuration: "38s", animationDirection: "reverse" }}
          viewBox="0 0 2880 320"
          preserveAspectRatio="none"
          fill="currentColor"
        >
          <path d="M0,180 C240,120 480,240 720,180 C960,120 1200,240 1440,180 C1680,120 1920,240 2160,180 C2400,120 2640,240 2880,180 L2880,320 L0,320 Z" />
        </svg>
        <svg
          className="animate-wave-drift absolute bottom-0 left-0 h-72 w-[200%] text-brand-700/[0.06] dark:text-brand-200/[0.06]"
          style={{ animationDuration: "32s" }}
          viewBox="0 0 2880 320"
          preserveAspectRatio="none"
          fill="currentColor"
        >
          <path d="M0,140 C240,200 480,80 720,140 C960,200 1200,80 1440,140 C1680,200 1920,80 2160,140 C2400,200 2640,80 2880,140 L2880,320 L0,320 Z" />
        </svg>
      </div>
    );
  }
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      <svg
        className="animate-wave-drift absolute bottom-0 left-0 h-16 w-[200%] text-brand-600/[0.10] dark:text-brand-400/[0.12]"
        style={{ animationDuration: "26s" }}
        viewBox="0 0 2880 120"
        preserveAspectRatio="none"
        fill="currentColor"
      >
        <path d="M0,55 C240,75 480,35 720,55 C960,75 1200,35 1440,55 C1680,75 1920,35 2160,55 C2400,75 2640,35 2880,55 L2880,120 L0,120 Z" />
      </svg>
      <svg
        className="animate-wave-drift absolute bottom-0 left-0 h-12 w-[200%] text-brand-500/[0.08] dark:text-brand-300/[0.08]"
        style={{ animationDuration: "38s", animationDirection: "reverse" }}
        viewBox="0 0 2880 120"
        preserveAspectRatio="none"
        fill="currentColor"
      >
        <path d="M0,62 C240,42 480,82 720,62 C960,42 1200,82 1440,62 C1680,42 1920,82 2160,62 C2400,42 2640,82 2880,62 L2880,120 L0,120 Z" />
      </svg>
    </div>
  );
}
