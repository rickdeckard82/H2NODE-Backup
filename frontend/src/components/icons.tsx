import type { ReactNode } from "react";

type IconProps = { className?: string };

function S({ className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      className={className ?? "h-4 w-4"}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const HomeIcon = (p: IconProps) => (
  <S {...p}>
    <path d="M3 12l9-9 9 9" />
    <path d="M5 10v10a1 1 0 0 0 1 1h3v-6h6v6h3a1 1 0 0 0 1-1V10" />
  </S>
);

export const ServerIcon = (p: IconProps) => (
  <S {...p}>
    <rect x="3" y="4" width="18" height="7" rx="1.5" />
    <rect x="3" y="13" width="18" height="7" rx="1.5" />
    <path d="M7 7.5h.01M7 16.5h.01" />
  </S>
);

export const LayersIcon = (p: IconProps) => (
  <S {...p}>
    <path d="M12 3 3 8l9 5 9-5-9-5Z" />
    <path d="M3 13l9 5 9-5" />
  </S>
);

export const UsersIcon = (p: IconProps) => (
  <S {...p}>
    <path d="M16 19v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M22 19v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </S>
);

export const IdCardIcon = (p: IconProps) => (
  <S {...p}>
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <circle cx="9" cy="11" r="2.5" />
    <path d="M5.5 16.5c.7-1.5 2-2.5 3.5-2.5s2.8 1 3.5 2.5" />
    <path d="M14.5 9.5h4M14.5 13h4" />
  </S>
);

export const ShieldCheckIcon = (p: IconProps) => (
  <S {...p}>
    <path d="M12 3l7 3v5c0 4.5-3 8.5-7 10-4-1.5-7-5.5-7-10V6l7-3Z" />
    <path d="M9 12l2 2 4-4" />
  </S>
);

export const BarChartIcon = (p: IconProps) => (
  <S {...p}>
    <path d="M3 3v18h18" />
    <rect x="7" y="12" width="3" height="6" />
    <rect x="12" y="8" width="3" height="10" />
    <rect x="17" y="4" width="3" height="14" />
  </S>
);

export const ActivityIcon = (p: IconProps) => (
  <S {...p}>
    <path d="M3 12h4l3 8 4-16 3 8h4" />
  </S>
);

export const ClipboardIcon = (p: IconProps) => (
  <S {...p}>
    <rect x="8" y="3" width="8" height="4" rx="1" />
    <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2" />
    <path d="M9 12h6M9 16h6" />
  </S>
);

export const SettingsIcon = (p: IconProps) => (
  <S {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 13.5a1.65 1.65 0 0 0 .33 1.82l.05.05a2 2 0 1 1-2.83 2.83l-.05-.05a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.05.05a2 2 0 1 1-2.83-2.83l.05-.05a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.05-.05a2 2 0 1 1 2.83-2.83l.05.05a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.05-.05a2 2 0 1 1 2.83 2.83l-.05.05a1.65 1.65 0 0 0-.33 1.82V13a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
  </S>
);

export const UserCogIcon = (p: IconProps) => (
  <S {...p}>
    <circle cx="10" cy="7" r="4" />
    <path d="M2 21v-1.5A4.5 4.5 0 0 1 6.5 15H11" />
    <circle cx="18" cy="17" r="3" />
    <path d="M18 13.6v.9M18 19.5v.9M21.2 17h-.9M15.7 17h-.9M20.1 14.9l-.6.6M16.5 18.5l-.6.6M20.1 19.1l-.6-.6M16.5 15.5l-.6-.6" />
  </S>
);

export const EyeIcon = (p: IconProps) => (
  <S {...p}>
    <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7Z" />
    <circle cx="12" cy="12" r="3" />
  </S>
);

export const MailIcon = (p: IconProps) => (
  <S {...p}>
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <path d="m4 7 8 6 8-6" />
  </S>
);

export const KeyIcon = (p: IconProps) => (
  <S {...p}>
    <circle cx="8" cy="15" r="4" />
    <path d="m10.5 12.5 8-8M16 4l3 3M13 7l3 3" />
  </S>
);

export const DatabaseIcon = (p: IconProps) => (
  <S {...p}>
    <ellipse cx="12" cy="5" rx="8" ry="3" />
    <path d="M4 5v6c0 1.66 3.58 3 8 3s8-1.34 8-3V5" />
    <path d="M4 11v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6" />
  </S>
);

export const HardDriveIcon = (p: IconProps) => (
  <S {...p}>
    <path d="M22 12H2" />
    <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z" />
    <path d="M6 16h.01M10 16h.01" />
  </S>
);

export const ArchiveIcon = (p: IconProps) => (
  <S {...p}>
    <rect x="2" y="4" width="20" height="5" rx="1" />
    <path d="M4 9v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9" />
    <path d="M10 13h4" />
  </S>
);

export const DownloadIcon = (p: IconProps) => (
  <S {...p}>
    <path d="M12 3v12" />
    <path d="m7 10 5 5 5-5" />
    <path d="M5 21h14" />
  </S>
);

export const LockIcon = (p: IconProps) => (
  <S {...p}>
    <rect x="4" y="11" width="16" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </S>
);

export const RouterIcon = (p: IconProps) => (
  <S {...p}>
    <rect x="2" y="13" width="20" height="8" rx="2" />
    <path d="M6 17h.01M10 17h.01" />
    <path d="M15 13V9" />
    <path d="M12 6a4 4 0 0 1 6 0" />
    <path d="M9.5 3.5a7.5 7.5 0 0 1 11 0" />
  </S>
);

export const HelpIcon = (p: IconProps) => (
  <S {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7" />
    <path d="M12 17h.01" />
  </S>
);

export const ICONS = {
  home: HomeIcon,
  database: DatabaseIcon,
  server: ServerIcon,
  layers: LayersIcon,
  users: UsersIcon,
  idCard: IdCardIcon,
  shield: ShieldCheckIcon,
  barChart: BarChartIcon,
  activity: ActivityIcon,
  clipboard: ClipboardIcon,
  settings: SettingsIcon,
  userCog: UserCogIcon,
  eye: EyeIcon,
  mail: MailIcon,
  key: KeyIcon,
  hardDrive: HardDriveIcon,
  archive: ArchiveIcon,
  download: DownloadIcon,
  lock: LockIcon,
  router: RouterIcon,
  help: HelpIcon,
} as const;

export type IconName = keyof typeof ICONS;
