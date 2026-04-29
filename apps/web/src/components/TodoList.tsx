import { CheckCircle2, Circle, LoaderCircle } from "lucide-react";

import type { TodoItem } from "../types/api";

export function TodoList({ todos }: { todos: TodoItem[] }) {
  if (!todos.length) return <div className="empty-state">No todos yet</div>;
  return (
    <div className="todo-list">
      {todos.map((todo) => {
        const Icon = todo.status === "completed" ? CheckCircle2 : todo.status === "active" ? LoaderCircle : Circle;
        return (
          <div className="todo-row" data-status={todo.status} key={todo.id}>
            <Icon className="todo-icon" />
            <span>{todo.text}</span>
          </div>
        );
      })}
    </div>
  );
}

