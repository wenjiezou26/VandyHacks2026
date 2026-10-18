# LetterLens live demo script

Persona: **Mei-ling Chen (陈美玲), 74, Flushing, Queens. Lives alone, speaks
Mandarin, reads Simplified Chinese, very little English. Already
receives SNAP. Has never heard of the Medicare Savings Program and
assumes her savings disqualify her.** See `demo/fixtures/SPEC.md` for
the full fixture spec and expected numbers.

Target: under 3 minutes for the core FIND → KEEP → PROTECT walkthrough,
plus an optional 30-second bonus proving the pipeline isn't hardcoded,
leaving room for Q&A.

## Before you go on stage

**Setup (do this ~10 min before your slot):**

```bash
# Terminal 1 -- backend, pointed at a DB seeded with the full story
cd LetterLens
python3 scripts/seed_demo.py --step protect   # fixtures 1-4, QMB active
DATABASE_URL="sqlite:///demo/demo_letterlens.db" MOCK_MODE=true DEMO_MODE=true \
  uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2 -- frontend
cd LetterLens/frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

Sign in with phone **718-555-0100** (the demo OTP is shown on screen,
no real SMS is sent) to land on Mei-ling's fully-seeded account --
useful for jumping straight to KEEP or PROTECT if you're short on time,
or as an instant recovery if something breaks mid-demo. For the live
walkthrough below, start from a **fresh** sign-in with a different
phone number instead, so the audience watches each letter get read in
real time rather than seeing it all pre-loaded.

- `--step find` seeds only the SSA letter + bank statement.
  `--step keep` adds the HRA notice. `--step protect` (above) adds QMB
  enrollment + the clinic bill -- pick whichever moment you want to
  jump straight to.
- Phone demo: find your Mac's Wi-Fi IP (`ipconfig getifaddr en0`) and
  open `http://<that-ip>:5173` in **iPhone Safari** (not Chrome -- Add
  to Home Screen only works in Safari). The frontend calls the API
  through its own `/api` proxy, so the phone only ever talks to port
  5173.
- **Risk**: some venue/campus Wi-Fi has client isolation and will block
  your phone from reaching your laptop even on the same network. Test
  this *before* you're on stage. If it fails, present from the laptop
  browser at `localhost:5173` instead.
- **Fallback if anything breaks live**: sign in with 718-555-0100 (seeded
  above) to skip straight to a working screen, or `python3
  demo/run_demo.py` for a scripted terminal transcript of the whole
  flow (older persona, still a valid safety net for "does the backend
  actually work" if the UI itself is the problem).

## The pitch frame (say this before you start clicking)

> "Mei-ling is 74, lives alone in Flushing, and reads Chinese, not
> English. She already gets SNAP, but she's never heard of the Medicare
> Savings Program -- she assumes her $40,000 in savings disqualifies
> her. It doesn't; New York doesn't count savings for MSP. Nationally,
> 6.6 million older adults are missing out on Medicare Savings Programs
> they already qualify for. They aren't ineligible. The letters are in
> English, the forms are confusing, and they're guessing wrong about
> their own eligibility. LetterLens reads her letters, explains them in
> Chinese, and **fills in the application for her. Her only job is to
> say yes.**"

Mention early: **"Every number here is checked against SSA/NY State
limits by a deterministic Python rules engine. The AI never decides
eligibility; it only explains."**

## Walkthrough (FIND → KEEP → PROTECT)

**1. Language picker**: tap 中文. *"Five languages, built Chinese-first
for Flushing and Chinatown."*

**2. Sign in**: type any 10-digit number, tap 给我发验证码, type the code
shown in the green box, tap 登录. *"Before she uploads anything
personal, we verify it's her phone. That's how we answer 'why should
she trust this app with her documents?' In production it's a real text
message; for the demo the code is shown on screen."*

**3. Upload the SSA letter** (`demo/fixtures/01_ssa_benefit_letter.png`):
tap the camera. *"OCI Document Understanding reads it, OCI Generative
AI classifies it, pulls out her name, address, birthdate, and benefit
amount, and explains it in Chinese -- the numbers stay exactly as
printed. A mistranslated dollar amount is a real-world harm."*

**4. Upload the bank statement** (`02_bank_statement.png`): *"$40,000
in savings. On paper that sounds disqualifying. It isn't: New York
doesn't count savings for the Medicare Savings Program. The app says so
explicitly -- and it uses her Social Security letter's **gross** benefit
for the eligibility math, not the bank's smaller net deposit after the
Medicare premium came out. Using the wrong one would push her over the
limit on paper."*

**5. 福利 tab (benefits)**: two quick questions appear first --
monthly work income (0) and married-and-living-together (否) -- *"those
are the only two facts no letter answers. Everything else, the app
already knows."* Then: **QMB likely ($202.90/mo, $2,434.80/yr), Extra
Help automatic via QMB.** Expand 原因 / 使用的数字 on the QMB card:
*"Every result shows its numbers, the rule applied, and 'Final decision
is made by NY State / HRA / SSA.'"*

**6. Tap 申请 MSP + Extra Help**: *"The application only asks what it
genuinely doesn't know yet."* Three questions: date of birth (from the
SSA letter, so just confirm it), Medicare number, household size.
*"That's it -- down from nine questions to three, because the letters
and the sign-in already answered the rest."*

**7. Review**: *"Every answer, and where it came from: 来自您的社会安全局
信件, from her Social Security letter; 您告诉我们的, she told us."* She
can tap 修改 on anything. Sign with a finger, then tap **是的，帮我提交**.
*"The AI does the work. She reviews once and says yes."*

**8. Upload the HRA SNAP notice** (`03_hra_snap_recert_notice.png`):
back on 首页. *"She's recertifying SNAP, not applying fresh -- the app
knows the difference."* On 福利, SNAP now shows **已经在享受 (already
enrolled)**, not "likely eligible" -- that would be a confusing, wrong
framing for someone already receiving it. A reminder appears: the
recertification deadline, counting down. Open 申请材料 (application
pack): the document checklist shows ✅ **have** (proof of income, from
the SSA letter), 🟡 **partial** (rent, utilities, medical expenses --
visible as payments on the bank statement, but the actual bill/lease/
receipt is still better), and ⬜ **missing** (proof of identity).

**9. PROTECT**: toggle 我已加入 QMB on 首页 (or it's already on if you
seeded with `--step protect`), then upload the clinic bill
(`04_clinic_bill.png`). *"Two charges on this bill: a $27.42 Medicare
coinsurance, and a $10 records-copy fee."* The app flags **only** the
$27.42 -- a QMB member can't legally be billed Medicare cost-sharing --
and leaves the $10 alone, because it's explicitly not a Medicare
service. *"It's not flagging everything on the page. It's reading what
each line actually is."* A dispute letter is drafted in English and
Chinese side by side.

**10. (If a document is missing) Caseworker handoff**: open
`/caseworker` in a second tab. Type a note and tap **Request info** --
back on her screen: 社工需要您补充材料 with the note, a 补充后重新提交
button, and the same review/sign flow. Or tap **Approve & send** for
the short version: 已提交, with a confirmation number and a timeline
(sent → state review → decision within 45 days).

Be upfront about the grey "演示" note on that screen: *"No agency
accepts filings from apps today. In production this goes through an
authorized-representative partner, like a community organization."*

## Bonus (30 seconds): proving it isn't hardcoded

Sign in as a different phone number and upload
`demo/fixtures/05_ssa_letter_variant.png` with the language set to
Russian. *"Same letter layout, completely different person -- Elena
Petrova, a different benefit amount, a different birthdate."* Her
countable income lands in a different Medicare Savings Program tier
(QI instead of QMB) and Extra Help is still automatic. *"The pipeline
read the pixels, not the filename -- it's not a lookup table with one
hardcoded answer."*

## If a judge asks...

- **"What happens if OCI Document Understanding is down?"** → Point at
  `MOCK_MODE`. Every OCI call (OCR, classify, extract, explain, draft,
  translate) has an offline deterministic fallback, same API surface.
  The demo never depends on live network access to Oracle Cloud.
- **"How do you stop the AI from hallucinating a wrong dollar amount?"**
  → `app/number_guard.py` -- every GenAI explanation is checked against
  its source facts; an invented number raises an error before it ever
  reaches the user.
- **"Does it really submit?"** → No, and the app says so on screen. No NY
  State / HRA / SSA API accepts third-party filings. Everything up to the
  send is real: the pre-filled form, the signature, the caseworker
  handoff. The last hop would go through an authorized-representative
  partner.
- **"How do you know it's really her?"** → Phone one-time code before
  any upload. Today the code is shown on screen (no SMS provider wired);
  swapping in a real SMS sender is one function, `app/auth/service.py`
  `send_code()`.
- **"What if the documents aren't enough to decide?"** → That's the
  caseworker handoff (step 10): instead of guessing or failing silently,
  the application routes to a human who reviews exactly the gap, not the
  whole file.
- **"What's still missing?"** → Be honest: SMS delivery for the sign-in
  code, real agency filing, caseworker accounts (one shared key today),
  and the per-field real-OCI golden test (`tests/test_fixtures_live.py`)
  is opt-in (`RUN_LIVE=1`) rather than part of every test run. Real OCI
  mode itself has been run end to end against the team's tenancy with
  `scripts/check_oci.py`. All flagged inline in the code, not hidden.

## Time budget

Steps 1-9 above run in roughly 2 minutes of actual clicking if you
don't pause to narrate every line -- practice it once end to end so the
live version isn't the first time you've done it back to back. The
bonus adds 30 seconds; skip it if you're tight on time.
