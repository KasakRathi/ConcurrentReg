import { ButtonLink } from "@/components/ui/Button";

export default function NotFound() {
  return (
    <main className="grid min-h-screen place-items-center px-4 text-center">
      <div>
        <p className="eyebrow">404</p>
        <h1 className="display mt-3 text-4xl text-ink-50">This route does not exist.</h1>
        <div className="mt-8 flex justify-center gap-3">
          <ButtonLink to="/" variant="secondary">Home</ButtonLink>
          <ButtonLink to="/dashboard" variant="primary">Dashboard</ButtonLink>
        </div>
      </div>
    </main>
  );
}
