/**
 * Logotipo do Pulse Backup. Alterna entre a versão clara e a escura conforme o
 * tema do navegador (prefers-color-scheme). Arquivos em `public/`.
 */
export function Logo({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <>
      <img src="/logo-light.svg" alt="Pulse Backup" className={`${className} block object-contain dark:hidden`} />
      <img src="/logo-dark.svg" alt="Pulse Backup" className={`${className} hidden object-contain dark:block`} />
    </>
  );
}
