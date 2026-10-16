import { ArrowRight, Check } from "lucide-react"
import { AmberLogo } from "./AmberLogo"

function LandingPage({ onContinue }: { onContinue: () => void }) {
  return (
    <main className="relative min-h-screen overflow-hidden bg-[#fbfdff] text-[#101a3a]">
      <div className="pointer-events-none absolute -left-48 top-24 h-[420px] w-[420px] rounded-full bg-[#eaf2ff] blur-3xl" />
      <div className="pointer-events-none absolute -right-36 bottom-0 h-[480px] w-[480px] rounded-full bg-[#eef4ff] blur-3xl" />

      <nav className="relative z-40 mx-auto flex max-w-[1220px] items-center justify-between px-6 py-5 lg:px-10">
        <button
          type="button"
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          aria-label="Amber home"
        >
          <AmberLogo compact />
        </button>
        <button
          className="rounded-full border border-[#c9d8ed] bg-white/80 px-5 py-2.5 text-sm font-bold text-[#2f65bd] shadow-[0_8px_22px_rgba(49,79,132,0.07)] backdrop-blur-sm transition hover:-translate-y-0.5 hover:border-[#7ca3e7]"
          type="button"
          onClick={onContinue}
        >
          Open dashboard
        </button>
      </nav>

      <section className="relative z-10 mx-auto grid min-h-[calc(100dvh-96px)] max-w-[1220px] items-center gap-4 px-6 pb-10 pt-8 lg:grid-cols-[0.92fr_1.08fr] lg:gap-10 lg:px-10 lg:pb-14 lg:pt-4">
        <div className="relative z-30 max-w-[610px]">
          {/* <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-[#d6e3f7] bg-white/80 px-4 py-2 text-xs font-extrabold uppercase tracking-[0.12em] text-[#5471a5] shadow-[0_8px_24px_rgba(55,83,133,0.06)] backdrop-blur-sm">
            <span className="h-2 w-2 rounded-full bg-[#3479f5] shadow-[0_0_0_4px_rgba(52,121,245,0.12)]" />
            Your AI meeting agent
          </div> */}
          <h1 className="text-[50px] font-extrabold leading-[1.02] tracking-[-0.055em] sm:text-[66px] lg:text-[74px]">
            Stay present,{" "}
            <span className="block bg-gradient-to-r from-[#246fdc] via-[#3479f5] to-[#79a7ff] bg-clip-text text-transparent">
              remember everything.
            </span>
          </h1>
          <p className="mt-6 max-w-[560px] text-base leading-7 text-[#66738d] sm:text-lg sm:leading-8">
            Schedule Amber or paste a meeting link. Amber joins your Google
            Meet, Zoom, or Microsoft Teams call, then captures the notes,
            decisions, and next steps for you.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-4">
            <button
              className="group inline-flex items-center gap-3 rounded-full bg-[#3479f5] px-7 py-4 text-base font-bold text-white shadow-[0_16px_34px_rgba(52,121,245,0.28)] transition hover:-translate-y-0.5 hover:bg-[#246cdf]"
              type="button"
              onClick={onContinue}
            >
              Start with Amber
              <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-1" />
            </button>
            {/* <span className="text-sm font-semibold text-[#7a879d]">
              You manage. Amber joins.
            </span> */}
          </div>
          <div className="mt-8 flex flex-wrap gap-x-5 gap-y-2 text-sm font-semibold text-[#53617a]">
            {["Google Meet", "Zoom", "Microsoft Teams"].map((platform) => (
              <span key={platform} className="inline-flex items-center gap-1.5">
                <span className="grid h-4 w-4 place-items-center rounded-full bg-[#e6f4ec] text-[#25815a]">
                  <Check className="h-2.5 w-2.5" strokeWidth={3} />
                </span>
                {platform}
              </span>
            ))}
          </div>
        </div>

        <div
          className="relative mx-auto h-[430px] w-full max-w-[680px] sm:h-[520px] lg:-mr-8 lg:h-[570px]"
          role="img"
          aria-label="Amber joins an online meeting for the operator"
        >
          <div className="absolute left-[12%] top-[7%] aspect-square w-[78%] rounded-full border border-white/80 bg-gradient-to-br from-[#dceaff] via-[#f1f6ff] to-white shadow-[0_34px_90px_rgba(59,101,174,0.18)]" />
          <div className="absolute left-[20%] top-[16%] h-[60%] w-[64%] rounded-full bg-[#cfe0ff]/50 blur-3xl" />

          <img
            className="absolute left-0 top-[8%] z-10 w-[61%] object-contain drop-shadow-[0_22px_36px_rgba(44,78,137,0.2)] sm:left-[1%] sm:top-[10%] sm:w-[59%]"
            src="/assets/meet.svg"
            alt=""
          />

          <div className="amber-hero-agent absolute bottom-[1%] left-[34%] z-20 w-[62%] sm:left-[35%] sm:w-[58%]">
            <div className="absolute bottom-1 left-1/2 h-12 w-[80%] -translate-x-1/2 rounded-[50%] bg-[#3d70c4]/30 blur-xl sm:h-14" />
            <img
              className="relative w-full object-contain drop-shadow-[0_26px_26px_rgba(36,69,126,0.3)]"
              src="/assets/amber-home-agent.svg"
              alt=""
            />
          </div>

          <div className="absolute right-0 top-[4%] z-30 flex items-center gap-3 rounded-2xl border border-white bg-white/90 px-4 py-3 shadow-[0_16px_40px_rgba(49,79,132,0.14)] backdrop-blur-md sm:right-[1%] sm:top-[8%]">
            <span className="relative flex h-9 w-9 items-center justify-center rounded-full bg-[#e8f7ef]">
              <span className="absolute h-2.5 w-2.5 animate-ping rounded-full bg-[#35a873]/40" />
              <span className="relative h-2.5 w-2.5 rounded-full bg-[#35a873]" />
            </span>
            <span>
              <span className="block text-xs font-extrabold text-[#263653]">
                Amber is ready
              </span>
              <span className="mt-0.5 block text-[11px] font-semibold text-[#8490a5]">
                Send now or schedule
              </span>
            </span>
          </div>
        </div>
      </section>
    </main>
  )
}

