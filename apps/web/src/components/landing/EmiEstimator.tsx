import { useMemo, useState } from "react";

const inr = (value: number) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);

/** Same reducing-balance formula the core service uses; display only. */
function emiFor(principal: number, annualRate: number, months: number): number {
  const r = annualRate / 1200;
  if (r === 0) return principal / months;
  return (principal * r * (1 + r) ** months) / ((1 + r) ** months - 1);
}

interface SliderProps {
  id: string;
  label: string;
  value: number;
  display: string;
  min: number;
  max: number;
  step: number;
  hint: [string, string];
  onChange: (value: number) => void;
}

function Slider({ id, label, value, display, min, max, step, hint, onChange }: SliderProps) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className="text-[13px] font-medium text-slate-700">
          {label}
        </label>
        <span className="rounded-md bg-amber-100 px-2 py-0.5 text-[13px] font-semibold tabular-nums text-amber-950">
          {display}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-valuetext={display}
        className="mt-3 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-blue-100 accent-blue-700"
      />
      <div className="mt-1 flex justify-between text-[11px] text-slate-400">
        <span>{hint[0]}</span>
        <span>{hint[1]}</span>
      </div>
    </div>
  );
}

export function EmiEstimator() {
  const [amount, setAmount] = useState(300000);
  const [rate, setRate] = useState(12);
  const [months, setMonths] = useState(36);

  const { emi, totalPayment, totalInterest, interestShare } = useMemo(() => {
    const value = emiFor(amount, rate, months);
    const total = value * months;
    return {
      emi: value,
      totalPayment: total,
      totalInterest: total - amount,
      interestShare: ((total - amount) / total) * 100,
    };
  }, [amount, rate, months]);

  return (
    <section id="calculator" className="border-y border-blue-100 bg-white py-20 sm:py-24">
      <div className="mx-auto max-w-6xl px-5">
        <div className="grid gap-10 lg:grid-cols-[1fr_1fr] lg:gap-16">
          <div>
            <p className="text-[11.5px] font-semibold uppercase tracking-[0.18em] text-blue-700">
              Estimator
            </p>
            <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-slate-900 sm:text-[2.2rem]">
              See the shape of the repayment
            </h2>
            <p className="mt-4 text-[15px] leading-relaxed text-slate-600">
              An indicative EMI on a reducing balance. The number on a sanction letter is computed
              server-side from the versioned policy — this panel is for orientation before you ask
              the assistant.
            </p>

            <div className="mt-8 space-y-7">
              <Slider
                id="amount"
                label="Loan amount"
                value={amount}
                display={inr(amount)}
                min={50000}
                max={2000000}
                step={10000}
                hint={["₹50,000", "₹20,00,000"]}
                onChange={setAmount}
              />
              <Slider
                id="rate"
                label="Interest rate (p.a.)"
                value={rate}
                display={`${rate}%`}
                min={8}
                max={24}
                step={0.5}
                hint={["8%", "24%"]}
                onChange={setRate}
              />
              <Slider
                id="tenure"
                label="Tenure"
                value={months}
                display={`${months} months`}
                min={6}
                max={60}
                step={6}
                hint={["6 months", "60 months"]}
                onChange={setMonths}
              />
            </div>
          </div>

          <div className="rounded-2xl border border-blue-200 bg-gradient-to-b from-blue-800 to-blue-900 p-6 text-white shadow-[0_30px_60px_-40px_rgba(29,78,216,0.9)] sm:p-8">
            <p className="text-[11.5px] font-semibold uppercase tracking-[0.16em] text-amber-300">
              Monthly EMI
            </p>
            <p className="mt-1 text-[2.6rem] font-semibold leading-none tracking-tight tabular-nums">
              {inr(emi)}
            </p>

            <dl className="mt-7 space-y-3 border-t border-white/15 pt-5 text-[13.5px]">
              <div className="flex justify-between">
                <dt className="text-blue-100/80">Principal</dt>
                <dd className="font-medium tabular-nums">{inr(amount)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-blue-100/80">Total interest</dt>
                <dd className="font-medium tabular-nums">{inr(totalInterest)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-blue-100/80">Total payable</dt>
                <dd className="font-semibold tabular-nums text-amber-300">{inr(totalPayment)}</dd>
              </div>
            </dl>

            <div className="mt-6">
              <div className="flex h-2.5 overflow-hidden rounded-full bg-white/15">
                <div
                  className="bg-white"
                  style={{ width: `${100 - interestShare}%` }}
                  aria-hidden="true"
                />
                <div className="bg-amber-400" style={{ width: `${interestShare}%` }} aria-hidden="true" />
              </div>
              <div className="mt-2 flex justify-between text-[11.5px] text-blue-100/70">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-white" />
                  Principal
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-amber-400" />
                  Interest
                </span>
              </div>
            </div>

            <p className="mt-6 text-[11.5px] leading-relaxed text-blue-100/60">
              Indicative only. Eligibility, rate and final EMI are decided by the credit policy, not
              by this panel.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
