import { Header } from "./components/Header";
import { Gather } from "./routes/Gather";
import { PresetPage } from "./routes/Preset";
import { Review } from "./routes/Review";
import { navigate, useRoute } from "./lib/router";

export function App() {
  const route = useRoute();
  return (
    <div className="min-h-dvh bg-paper text-ink">
      <Header />
      <main className="mx-auto w-full max-w-[1080px] px-5 pb-24 sm:px-8">
        {route.name === "gather" ? <Gather /> : null}
        {route.name === "preset" ? <PresetPage /> : null}
        {route.name === "run" ? <Review key={route.runId} runId={route.runId} /> : null}
        {route.name === "notfound" ? (
          <div className="py-16">
            <h1 className="font-serif text-[2.5rem] leading-none tracking-[-0.02em]">That page does not exist.</h1>
            <a
              href="/"
              className="mt-6 inline-block text-[15px] underline decoration-line underline-offset-4"
              onClick={(event) => {
                event.preventDefault();
                navigate("/");
              }}
            >
              Back to Gather
            </a>
          </div>
        ) : null}
      </main>
    </div>
  );
}
