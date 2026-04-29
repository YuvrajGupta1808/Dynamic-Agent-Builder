import { Bot, CheckCircle2, CircleAlert, FilePenLine, ListTodo, TerminalSquare } from "lucide-react";

import type { StreamEvent } from "../types/api";
import { Badge } from "./ui/badge";

const icons = {
  token: Bot,
  thinking: Bot,
  update: CheckCircle2,
  custom: CheckCircle2,
  todo: ListTodo,
  tool_call: TerminalSquare,
  subagent: Bot,
  file_change: FilePenLine,
  approval_required: CircleAlert,
  error: CircleAlert,
  done: CheckCircle2,
};

export function EventTimeline({ events }: { events: StreamEvent[] }) {
  if (!events.length) return <div className="empty-state">Stream events will appear here</div>;
  return (
    <div className="timeline">
      {events.slice(-80).map((event) => {
        const Icon = icons[event.type];
        return (
          <div className="timeline-row" key={`${event.runId}-${event.sequence}`}>
            <Icon className="timeline-icon" />
            <div className="timeline-body">
              <div className="timeline-title">
                <span>{event.message || event.type}</span>
                <Badge>{event.source}</Badge>
              </div>
              {event.type !== "token" && <pre>{JSON.stringify(event.data, null, 2)}</pre>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
