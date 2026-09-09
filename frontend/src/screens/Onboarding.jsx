import { useState } from "react";
import { Card, FatPill } from "../components/ui.jsx";
import { api, session } from "../lib/api.js";
import { inr } from "../lib/format.js";

/* Opening the shop for the first time.
 *
 * Three steps, because a form with fifteen fields is how you lose a 52-year-old
 * before he has seen the product work. Only the name is truly required; a GSTIN
 * fills in the state by itself, and the rest has defaults he can change later.
 *
 * Nothing is seeded. The catalogue and the contact list fill themselves in from
 * the first bills and khata pages he photographs — that is what the product is
 * *for*, so pretending to know his products on day one would be a lie. */

function Field({ label, hint, children }) {
  return (
    <label className="block px-[18px] py-[13px] border-b border-separator last:border-0">
      <span className="text-meta text-text-2">{label}</span>
      {children}
      {hint && <span className="block text-micro text-text-3 mt-1">{hint}</span>}
    </label>
  );
}

const input = "w-full bg-transparent text-body font-semibold outline-none mt-1 " +
  "placeholder:text-text-3 placeholder:font-normal";

export function Onboarding({ states = {}, onDone }) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({
    name: "", name_ta: "", gstin: "", state_code: "", address: "", phone: "",
    ca_name: "", ca_phone: "", ca_email: "",
    credit_limit: 50000, credit_days: 30, passcode: "", passcode2: "",
  });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const digits = (value) => value.replace(/[^0-9]/g, "").slice(0, 12);

  const derived = states[form.gstin.trim().slice(0, 2)];

  const canContinue = [
    form.name.trim().length >= 2,
    Boolean(form.gstin.trim() || form.state_code),
    form.passcode.length >= 4 && form.passcode === form.passcode2,
  ][step];

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const { passcode2, ...body } = form;
      const result = await api.setupShop({
        ...body,
        credit_limit: Number(body.credit_limit) || 50000,
        credit_days: Number(body.credit_days) || 30,
        gstin: body.gstin.trim() || null,
      });
      session.set(result.token);
      onDone(result.shop);
    } catch (err) {
      setError(err.message ?? "Could not open the shop");
      if (String(err.message).includes("GSTIN")) setStep(1);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen px-gutter pt-10 pb-10">
      <div className="flex gap-1.5 mb-6">
        {[0, 1, 2].map((i) => (
          <span key={i} className={`h-[3px] flex-1 rounded-full transition-colors
            ${i <= step ? "bg-ink" : "bg-fill-3"}`} />
        ))}
      </div>

      {step === 0 && (
        <div className="animate-rise">
          <h1 className="text-screen font-bold">Open your shop</h1>
          <p className="text-body text-text-2 mt-2 mb-5">
            Your shop. Your galla. Guarded.
          </p>
          <Card className="overflow-hidden">
            <Field label="Shop name">
              <input className={input} value={form.name} onChange={set("name")}
                     placeholder="Murugan Hardware" autoFocus />
            </Field>
            <Field label="In your language"
                   hint="Optional — shown alongside the English name">
              <input className={input} value={form.name_ta} onChange={set("name_ta")}
                     placeholder="முருகன் ஹார்டுவேர்" />
            </Field>
            <Field label="Where the shop is">
              <input className={input} value={form.address} onChange={set("address")}
                     placeholder="Thudiyalur, Coimbatore" />
            </Field>
            <Field label="Phone">
              <input className={input} value={form.phone} onChange={set("phone")}
                     placeholder="+91 98422 00000" inputMode="tel" />
            </Field>
          </Card>
        </div>
      )}

      {step === 1 && (
        <div className="animate-rise">
          <h1 className="text-screen font-bold">Tax details</h1>
          <p className="text-body text-text-2 mt-2 mb-5">
            These go on every quotation and on the monthly summary for your CA.
          </p>
          <Card className="overflow-hidden">
            <Field label="GSTIN"
                   hint={derived ? `${derived} — taken from your GSTIN`
                     : "15 characters, like 33AAMPM8712K1ZQ. Leave blank if you are not registered."}>
              <input className={`${input} uppercase tracking-wide`} value={form.gstin}
                     onChange={(e) => setForm((f) => ({
                       ...f, gstin: e.target.value.toUpperCase() }))}
                     placeholder="33AAMPM8712K1ZQ" autoCapitalize="characters" />
            </Field>
            {!form.gstin.trim() && (
              <Field label="State"
                     hint="Decides CGST/SGST against IGST on your bills">
                <select className={`${input} appearance-none`} value={form.state_code}
                        onChange={set("state_code")}>
                  <option value="">Choose your state</option>
                  {Object.entries(states).sort((a, b) => a[1].localeCompare(b[1]))
                    .map(([code, name]) => (
                      <option key={code} value={code}>{name}</option>
                    ))}
                </select>
              </Field>
            )}
            <Field label="Default credit limit for someone new"
                   hint={`Anyone new starts at ${inr(Number(form.credit_limit) || 0)}. You can change it per person later.`}>
              <input className={input} value={form.credit_limit} inputMode="numeric"
                     onChange={set("credit_limit")} />
            </Field>
            {/* All three are optional and the hints say so on each, not once at
                the top — a field with no "optional" beside it reads as required
                when the one above it is labelled. The monthly summary goes
                wherever there is an address for it; with neither, it waits in
                the app until the owner adds one. */}
            <Field label="Your CA's name"
                   hint="Optional — who receives the monthly summary">
              <input className={input} value={form.ca_name} onChange={set("ca_name")}
                     placeholder="CA Ramesh" />
            </Field>
            <Field label="Your CA's phone" hint="Optional">
              <input className={input} value={form.ca_phone} onChange={set("ca_phone")}
                     placeholder="+91 98422 11111" inputMode="tel" />
            </Field>
            <Field label="Your CA's email"
                   hint="Optional — a summary is easier to open on a computer">
              <input className={input} value={form.ca_email} onChange={set("ca_email")}
                     placeholder="ramesh@krishnanandco.in" inputMode="email"
                     autoCapitalize="none" autoCorrect="off" type="email" />
            </Field>
          </Card>
        </div>
      )}

      {step === 2 && (
        <div className="animate-rise">
          <h1 className="text-screen font-bold">Set a passcode</h1>
          <p className="text-body text-text-2 mt-2 mb-5">
            This is your ledger — what every customer owes you. The passcode keeps
            it yours. Four digits or more.
          </p>
          <Card className="overflow-hidden">
            <Field label="Passcode">
              <input className={`${input} tracking-[0.4em]`} value={form.passcode}
                     onChange={(e) => setForm((f) => ({
                       ...f, passcode: digits(e.target.value) }))}
                     type="password" inputMode="numeric" placeholder="••••" autoFocus />
            </Field>
            <Field label="Type it again"
                   hint={form.passcode2 && form.passcode !== form.passcode2
                     ? "These do not match"
                     : "Write it down somewhere safe — there is no reset."}>
              <input className={`${input} tracking-[0.4em]`} value={form.passcode2}
                     onChange={(e) => setForm((f) => ({
                       ...f, passcode2: digits(e.target.value) }))}
                     type="password" inputMode="numeric" placeholder="••••" />
            </Field>
          </Card>
          <p className="text-micro text-text-3 mt-4 leading-relaxed">
            Your shop starts empty. Photograph a supplier bill and the products add
            themselves; photograph a page of your khata and the accounts open
            themselves. Nothing is invented for you.
          </p>
        </div>
      )}

      {error && (
        <Card className="p-cardpad mt-3.5">
          <div className="flex gap-2 items-start">
            <span className="w-2 h-2 rounded-full bg-red mt-[6px] shrink-0" />
            <p className="text-row text-ink flex-1">{error}</p>
          </div>
        </Card>
      )}

      <div className="mt-6 space-y-1.5">
        <FatPill disabled={!canContinue || busy}
                 onClick={() => (step === 2 ? submit() : setStep(step + 1))}>
          {busy ? "Opening…" : step === 2 ? "Open my shop" : "Continue"}
        </FatPill>
        {step > 0 && (
          <FatPill variant="tertiary" onClick={() => setStep(step - 1)}>Back</FatPill>
        )}
      </div>
    </div>
  );
}

export function LockScreen({ shopName, shopNameTa, onUnlocked }) {
  const [passcode, setPasscode] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (code) => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.signIn(code);
      session.set(result.token);
      onUnlocked(result.shop);
    } catch (err) {
      setError(err.status === 429 ? err.message : "Wrong passcode");
      setPasscode("");
    } finally {
      setBusy(false);
    }
  };

  const press = (key) => {
    if (busy) return;
    if (key === "⌫") return setPasscode((p) => p.slice(0, -1));
    if (key === "→") return passcode.length >= 4 && submit(passcode);
    setPasscode((p) => (p.length >= 12 ? p : p + key));
  };

  return (
    <div className="min-h-screen flex flex-col justify-between px-gutter pt-16 pb-8">
      <div className="text-center animate-rise">
        <div className="w-[52px] h-[52px] rounded-full bg-ink mx-auto mb-4
                        flex items-center justify-center text-white text-tile">
          ₹
        </div>
        {/* His shop's name, not the product's. He should recognise his own
            counter before he is asked for anything. */}
        <div className="text-tile font-bold">{shopName || "Galla"}</div>
        {shopNameTa && shopNameTa !== shopName && (
          <div className="text-body text-text-3 mt-0.5">{shopNameTa}</div>
        )}

        <div className="flex justify-center gap-3 mt-8 h-[16px]">
          {Array.from({ length: Math.max(4, passcode.length) }).map((_, i) => (
            <span key={i} className={`w-[14px] h-[14px] rounded-full transition-colors
              ${i < passcode.length ? "bg-ink" : "bg-chevron"}`} />
          ))}
        </div>
        <p className={`text-row mt-4 h-5 ${error ? "text-red font-semibold" : "text-text-2"}`}>
          {error || "Enter your passcode"}
        </p>
      </div>

      {/* A keypad, not a text field. The owner is standing up, one-handed, in
          bad light — 72px targets beat whatever keyboard the OS offers. */}
      <div className="grid grid-cols-3 gap-2.5 mt-8">
        {["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "→"].map((key) => (
          <button
            key={key} type="button" onClick={() => press(key)}
            disabled={busy || (key === "→" && passcode.length < 4)}
            aria-label={key === "⌫" ? "Delete" : key === "→" ? "Unlock" : key}
            className={`h-[72px] rounded-input text-[24px] font-semibold
              active:opacity-70 disabled:opacity-30
              ${key === "→" ? "bg-ink text-white"
                : key === "⌫" ? "bg-fill-2 text-ink" : "bg-card text-ink"}`}
          >
            {busy && key === "→" ? "…" : key}
          </button>
        ))}
      </div>

      {/* Setup says "there is no reset" once, on a screen the owner sees for
          thirty seconds a year ago. This is where he needs to know it: he
          cannot sign in, and starting over asks for the same passcode he has
          lost. Better he learns that from us, standing at his counter, than by
          trying every four-digit number he can think of. */}
      <p className="text-micro text-text-3 text-center mt-6 leading-relaxed">
        Forgotten it? There is no reset — the passcode is not stored anywhere,
        not even here. Ask whoever set the shop up.
      </p>
    </div>
  );
}
