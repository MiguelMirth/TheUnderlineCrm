import { navigate, useRoute } from "../lib/router";

export function Header() {
  const route = useRoute();
  const runs = route.name === "gather" || route.name === "run";
  const preset = route.name === "preset";
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-paper">
      <div className="h-1 bg-ink" aria-hidden />
      <div className="mx-auto flex w-full max-w-[1080px] items-baseline justify-between gap-6 px-5 py-5 sm:px-8">
        <a
          href="/"
          onClick={(event) => {
            event.preventDefault();
            navigate("/");
          }}
          className="wordmark text-ink"
        >
          Mirth
        </a>
        <nav className="flex items-baseline gap-6 text-[15px]" aria-label="Sections">
          <NavLink href="/" active={runs}>
            Runs
          </NavLink>
          <NavLink href="/preset" active={preset}>
            Preset
          </NavLink>
        </nav>
      </div>
    </header>
  );
}

function NavLink({ href, active, children }: { href: string; active: boolean; children: string }) {
  return (
    <a
      href={href}
      aria-current={active ? "page" : undefined}
      onClick={(event) => {
        event.preventDefault();
        navigate(href);
      }}
      className={active ? "text-ink" : "text-ink-soft hover:text-ink"}
    >
      {children}
    </a>
  );
}
