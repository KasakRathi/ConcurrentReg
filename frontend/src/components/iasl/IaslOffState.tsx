import { Power } from "lucide-react";
import { CodeBlock } from "@/components/ui/CodeBlock";
import { EmptyState } from "@/components/ui/States";

/** IASL is optional and off by default. This says so plainly and shows how to turn it on; it never shows sample data. */
export function IaslOffState({ message }: { message?: string }) {
  return (
    <EmptyState
      icon={<Power className="size-6" aria-hidden />}
      title="IASL is switched off"
      action={
        <div className="mt-2 w-full max-w-xl space-y-3 text-left">
          <CodeBlock title="start the API with IASL on" code={"IASL_ENABLED=1 .venv/bin/uvicorn app.main:app --port 8000"} />
          <CodeBlock title="or start the whole demo with IASL on" code={"IASL=1 ./scripts/start_demo.sh"} />
        </div>
      }
    >
      <p>{message ?? "Nothing is installed on the request path, so requests behave exactly as they did before IASL existed."}</p>
      <p className="mt-2">Every setting and the safety rules are described in <span className="font-mono text-ink-100">docs/iasl/IASL_CONFIGURATION.md</span>. When IASL is on, this page shows the queue, the admission limit, the controller's state and every decision it makes.</p>
    </EmptyState>
  );
}
