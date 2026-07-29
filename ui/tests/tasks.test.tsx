import { render, screen } from "@testing-library/react";

import { TaskStatus } from "../src/features/tasks/TaskStatus";

test("renders stable Chinese deployment status labels", () => {
  const { rerender } = render(<TaskStatus status="running" />);
  expect(screen.getByText("执行中")).toBeInTheDocument();

  rerender(<TaskStatus status="manual_review" />);
  expect(screen.getByText("需人工确认")).toBeInTheDocument();
});
