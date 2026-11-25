import {
  CalendarDays,
  CheckSquare2,
  FileText,
  GitBranch,
  HardDrive,
  Mail,
  MessageSquare,
  NotebookTabs,
  type LucideIcon,
} from "lucide-react";

const icons: Record<string, LucideIcon> = {
  github: GitBranch,
  gmail: Mail,
  drive: HardDrive,
  calendar: CalendarDays,
  notion: NotebookTabs,
  todoist: CheckSquare2,
  slack: MessageSquare,
  microsoft: FileText,
};

export function serviceName(key: string): string {
  return (
    (
      {
        github: "GitHub",
        gmail: "Gmail",
        drive: "Google Drive",
        calendar: "Calendar",
        notion: "Notion",
        todoist: "Todoist",
        slack: "Slack",
        microsoft: "Microsoft 365",
      } as Record<string, string>
    )[key] ?? key
  );
}

export function ServiceMark({
  source,
  size = 18,
}: {
  source: string;
  size?: number;
}) {
  const Icon = icons[source] ?? FileText;
  return (
    <span className={`service-mark service-${source}`} aria-hidden="true">
      <Icon size={size} strokeWidth={1.8} />
    </span>
  );
}
