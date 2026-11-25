import { Reveal } from "@/components/ui/Reveal";
import { LogoMark } from "@/components/ui/Logo";

export function QuoteSection() {
  return (
    <section className="lp-wrap py-20 sm:py-28">
      <Reveal className="mx-auto flex max-w-[560px] flex-col items-center text-center">
        <span className="grid size-[100px] place-items-center rounded-full bg-white/[0.04] shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]"><LogoMark className="size-11" /></span>
        <blockquote className="mt-10 text-[24px] leading-9 text-white">
          Everything in front of the database decides who waits. The database decides who gets a seat.
        </blockquote>
        <p className="mt-9 text-[16px] text-[#f0f0f0]">The design principle</p>
        <p className="text-[14px] text-[#a1a4a5]">A paraphrase of the README (Day 3): the database remains the authority on correctness</p>
      </Reveal>
    </section>
  );
}
