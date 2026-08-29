# FOI Insights on AWS: costing model (AUD)

**Date:** 2026-08-28. **Status:** internal estimate, not for issue. **Basis:** review of the
Horizon costings, the FOI dashboard as deployed, and AWS list prices for Sydney
(ap-southeast-2). All figures AUD, ex GST, rounded to the nearest thousand where a line is
an estimate. 1 USD = 1.39 AUD (Wise mid-market, 2026-08-28).

## 1. What this reviews

Two things feed this model.

1. The Horizon costings. Discovery, pilot, APS-wide build, licence and hosting options
   priced in the Horizon cost model and its review.
2. The FOI dashboard as built. A public 12-page statistics dashboard with a
   session-gated chat and builder, running on the horizon stack on idc-1, calling the fleet
   author model by role.

The ask: implementation, software licensing, support, and AWS deployment in Australia, for
open-source models, non-Chinese, across dev, test and prod, with ongoing engineering
support to keep the stack patched and current. The path is: uplift the current cluster to
serve the replacement models in dev, then deploy test and prod to AWS.

## 2. The Horizon costings, reviewed

The Horizon cost model prices the workforce product at internal cost: discovery about
$128k, pilot about $420k, build about $3.46M, enterprise licence about $1.19M a year.
Services were repriced 2026-08-18 to a 30% margin floor: discovery $175k-$200k, pilot
$560k-$620k, build $4.6M-$5.2M (standing decision: anchor new proposals at $6M-$8M),
enterprise licence $1.9M-$2.4M a year, per-agency licence $50k-$180k a year. Hosting
options: Option B, AWS Australia at an HCF-certified facility, $6,950 a month all in.

The review of that model found defects that this FOI model must not repeat:

- Day rates were never measured. The model rates are charge-out shaped. An independent
  review derived loaded costs 18-46% lower. This model uses 80% of the Horizon rates and
  flags the number as unmeasured.
- The 15% labour contingency sits below published guidance. This model uses 20%.
- Security was committed in prose and funded nowhere. IRAP is excluded here and scoped
  separately, same guard as Horizon. A web application penetration test is funded as its
  own line.
- Zero marginal cost per tenant produced nonsense margins. Not relevant at one tenant,
  but the model keeps per-unit lines separate.
- The AI efficiency multiplier is load-bearing in Horizon. This model assumes no
  efficiency multiplier at all. Faster delivery is upside, not a line.

What carries over unchanged: the role rates table (at 80%), the structural guards, and the
finding that AWS Sydney is IRAP-assessed and CCSL-listed, so an OFFICIAL workload there is
routine.

## 3. The FOI dashboard as it runs today

The FOI dashboard is a POC on the horizon serving stack.

- FastAPI origin on idc-1, port 8097, behind Cloudflare Worker and tunnel. Public at
  foi.axoquant.com.
- 12 statistics pages computed from a pinned data.gov.au snapshot. No live fetch. A golden
  boot check refuses to serve wrong data.
- Chat, reports and risk views are session-gated. Statistics pages and /ask are public.
- The LLM is resolved by role: axoquant_llm.chat("author", ...) maps to the fleet haproxy
  front on idc-1:8012, which serves Qwen3.8-27B-FP8 (vLLM on idc-1 and idc-2). Qwen is
  Alibaba. It has to go.
- Retrieval is BM25 over a local corpus. No embedding model sits in the FOI path. The
  horizon platform bge-m3 and bge-reranker (BAAI, Beijing) are not touched by FOI today.
- Environments: dev is the workstation, prod is idc-1. There is no FOI test environment.
  Horizon has a preview environment on idc-2, but FOI does not use it.
- Auth is pilot-grade: PBKDF2 hashes in Postgres, four seeded accounts. Session secret in
  an env file. Fine for a pilot, not for production.
- Data handling: published statistics only. OFFICIAL. The internal risk views are the
  highest sensitivity in the app.

The fleet today: six nodes, idc-1 to idc-6. idc-1 runs 2x RTX 3090 (48 GB), idc-2 runs a
3090 plus a 3090 Ti (48 GB). Both serve the 27B FP8 model. idc-3/4 run embedders and a
judge on 3080s. The model fits in 48 GB with about 18 GB left for KV cache.

## 4. Model plan: non-Chinese open weights

The author role needs a non-Chinese open model with permissive terms. Candidates, with
weights and fit:

| Model | Origin | Licence | FP8 weights | 4-bit weights | Fits today (48 GB) |
|---|---|---|---|---|---|
| Llama 3.3 70B Instruct | Meta (US) | Llama 3.3 Community | ~70 GB | ~40 GB (AWQ) | AWQ yes, tight KV |
| Gemma 3 27B | Google (US) | Gemma Terms of Use | ~27 GB | ~17 GB | FP8 yes, 4-bit on one card |
| Mistral Small 3.2 24B | Mistral (FR) | Apache 2.0 | ~24 GB | ~14 GB | yes |
| gpt-oss-20b | OpenAI (US) | Apache 2.0 | ~20 GB | ~11 GB | yes |

Recommendation: Llama 3.3 70B AWQ as the author model. It matches the serving shape
the fleet already runs (about 40 GB of weights on 48 GB of VRAM, same as the old 80B Q4)
and it is the strongest open non-Chinese model in the class. Gemma 3 27B is the
single-GPU and concurrency option. Decide by benchmark, not by paper: run both through the
FOI governance suite (scope screen, jailbreak scan, builder spec generation) before the
swap. Budget two weeks for the evaluation.

Licence fees: zero for all four. The Llama licence has a 700M monthly active user
threshold and attribution terms. Gemma carries a prohibited-use list. Both are fine for
this workload; compliance is a review, not a payment.

The identity stovepipe text ("axoquant sovereign stack") already hides the vendor, so no
governance code needs to change for the swap. The role registry is fleet-wide: if the
author role moves for all products, the evaluation cost is shared. This model carries the
FOI slice plus its own re-testing.

## 5. Target architecture

Three environments, split by account under AWS Organizations (free):

| Environment | Where | Shape |
|---|---|---|
| dev | on-prem, uplifted cluster | idc-1 / idc-2, model eval and dev serving, local Postgres |
| test | AWS Sydney, test account | g6.xlarge or g5.2xlarge on a schedule, single-AZ RDS |
| prod | AWS Sydney, prod account | ALB + WAF, 2x t3.small across 2 AZ, Multi-AZ RDS, g5.12xlarge |

- Dev stays on the uplifted cluster. It is where the model swap happens and where new
  model releases get evaluated before test. No cloud meter.
- Test is a scaled copy of prod in a separate account: one app instance, single-AZ
  Postgres, one GPU instance on a schedule (260 hours a month, 12 hours x 22 days). It
  doubles as pre-prod.
- Prod runs two app instances across two AZs behind an ALB with WAF, Multi-AZ RDS, and
  the GPU instance. The app degrades honestly when the LLM is down (pages still render), so
  a single GPU instance with fast restart is acceptable in year one. A second instance in
  the other AZ is the upgrade path, not the start.
- Public path: keep the existing Cloudflare Worker and tunnel. The VPS front door plan
  exists if a department gateway blocks Cloudflare; it adds about $12 a month.

No L40S instances (g6e) are offered in Sydney, which removes the 48 GB single-card cloud
option. The Sydney GPU fleet is A10G (g5), L4 (g6), T4 (g4dn), A100 and H100 (p4d/p5).

## 6. Costing model

### 6.1 Assumptions

- FX 1 USD = 1.39 AUD. 730 hours a month.
- Day rates: Horizon model rates at 80% (derived loaded-cost basis, unmeasured): tech lead
  $1,470, ML engineer $1,280, data engineer $1,150, full-stack $1,090, delivery lead
  $1,220, security $2,300, support $900.
- LLM load: 300 monthly active users, 40 queries, 6,000 tokens in plus out per query,
  72M tokens a month. Pilot load today is far below this.
- AWS list prices, no negotiated discounts, no Enterprise Discount Program.

### 6.2 Implementation (one-off)

| Package | Days | Cost |
|---|---:|---:|
| Landing zone: 3 accounts, VPCs, IaC, CI/CD, KMS, SSM | TL 5 + DE 6 | $14,250 |
| Model swap: download, eval harness, prompt regression, governance re-test | ML 12 + FS 4 | $19,720 |
| App hardening: auth upgrade, secrets, WAF, alarms, backup restore | FS 8 + Sec 2 | $13,320 |
| Environment parity: containers, pipelines, test GPU scheduler | DE 4 + FS 3 | $7,870 |
| Data pipeline: quarterly data.gov.au refresh, golden boot re-check | DE 8 | $9,200 |
| Cutover and DR rehearsal | FS 4 + DE 2 | $6,660 |
| Security: web application penetration test (external) + documentation | Sec 6 + $18,000 | $31,800 |
| Delivery lead, 15% | 10 | $12,200 |
| Subtotal | 74 days | $115,020 |
| Contingency 20% | | $23,004 |
| **Total** | | **$138,000** |

Range: $110k to $170k depending on how much of the landing zone and auth work already
exists. The Horizon AWS migration plan covers some of this ground for the Horizon app; FOI
reuses the patterns, not the prices.

### 6.3 Cluster uplift (capital, dev and model lab)

| Option | What it buys | Cost |
|---|---|---:|
| Light | Second used RTX 3090 in idc-2 (48 GB pair) + 2 TB NVMe | $1,600 - $2,600 |
| Mid (recommended) | One used A6000 48 GB in a dev server: 70B AWQ with KV headroom, 27B FP8, eval harness | $10,000 - $13,000 |
| High | Two 48 GB cards (A6000 or RTX 6000 Ada): 70B FP8 lab, real concurrency testing | $20,000 - $28,000 |

Base case $12,000. Marginal power is small (the boxes are already powered). This is dev
capacity only. Prod compute lives on AWS under the base case; Option E moves it onto
owned boxes.

### 6.4 AWS run (monthly)

Instance matrix, ap-southeast-2, USD list per hour (Holori reading the AWS price list,
2026-08-27):

| Instance | GPUs | VRAM | On-demand | 1 yr Instance SP | 3 yr Instance SP |
|---|---|---:|---:|---:|---:|
| g6.xlarge | 1x L4 | 24 GB | $1.0464 | $0.6812 | $0.4803 |
| g5.2xlarge | 1x A10G | 24 GB | $1.5758 | $0.9928 | $0.6808 |
| g5.12xlarge | 4x A10G | 96 GB | $7.3747 | $4.6461 | $3.1859 |
| g6.12xlarge | 4x L4 | 96 GB | $5.9830 | $3.8949 | $2.7462 |

Model to instance: Llama 70B AWQ needs 48 GB plus KV, so g5.12xlarge with tensor parallel
4 (or g6.12xlarge). Llama 70B FP8 needs 96 GB: g6.12xlarge (L4 has FP8; A10G does not).
Gemma 27B at 4-bit fits g6.xlarge or g5.2xlarge.

Prod, monthly AUD:

| Line | USD | AUD |
|---|---:|---:|
| 2x t3.small app instances (2 AZ) | 38.5 | 54 |
| ALB + 4 LCU | 42.9 | 60 |
| RDS db.t4g.medium Multi-AZ + 20 GB gp3 | 167.0 | 232 |
| EBS app volumes | 2.3 | 3 |
| NAT gateway + 30 GB | 45.0 | 63 |
| CloudWatch logs and alarms | 10.0 | 14 |
| WAF | 12.0 | 17 |
| SES, Secrets Manager, KMS, Inspector, Route 53, S3 | 13.3 | 18 |
| Non-GPU subtotal | 331.0 | 460 |

GPU options on top, 24 x 7, AUD:

| Prod GPU | On-demand | 1 yr Instance SP | 3 yr Instance SP |
|---|---:|---:|---:|
| g5.12xlarge, Llama 70B AWQ (base) | 7,483 | 4,714 | 3,233 |
| g6.12xlarge, Llama 70B FP8 | 6,071 | 3,952 | 2,787 |
| g6.xlarge, Gemma 27B 4-bit (value) | 1,062 | 691 | 487 |

Prod totals: base case $7,943 a month on-demand, $5,174 with a 1 yr Instance SP, $3,693
with a 3 yr. Value case $1,522 on-demand, $1,151 with a 1 yr SP.

Test, monthly AUD: one t3.small ($27), single-AZ RDS ($117), NAT ($63), logs and smalls
($25): $232. GPU on a 260 hour schedule: g5.2xlarge $570, g6.xlarge $378. Test total about
$800 a month on g5.2xlarge, $610 on g6.xlarge. Skip the NAT gateway with VPC endpoints and
it drops another $60.

Dev AWS is nil; dev lives on the uplifted cluster. An optional parity sandbox (one
t3.small plus small RDS) is about $170 a month.

AWS Business Support: 10% of usage, minimum USD 100 a month. On the base case that is
about $620 a month with Savings Plans, $890 on-demand.

### 6.5 Software licensing (annual)

| Item | Cost |
|---|---:|
| Model licences (Llama, Gemma, Mistral) | $0 |
| Serving and runtime (vLLM, Postgres, FastAPI) | $0 |
| Observability, self-hosted Grafana and Loki | $0 |
| Observability, Grafana Cloud (optional) | $3,500 |
| Domain, DNS, certificates | $100 |
| Base total | $100 |

No licence fees anywhere in the open-source stack. The optional line is the only real
software money. No data feed costs: data.gov.au is free and the snapshot is pinned.

### 6.6 Engineering support: keep current (annual)

Keeping three environments patched and current is the line that is easiest to under-fund.
It covers: OS and dependency patches on the app instances and the dev cluster, CUDA,
driver and vLLM upgrades, quarterly model refresh, quarterly data.gov.au release
reconciliation (the ingest carries a curated agency rename map that needs upkeep each
release), IaC and pipeline maintenance, RDS minor upgrades, certificate and DNS upkeep,
CVE triage, on-call, the annual penetration test, and DR rehearsal.

Two cadences:

| Line | Lean | Recommended |
|---|---:|---:|
| Dependency and CVE patching, image rebuilds | 1 d/mo FS, 12d, $13,080 | 2 d/mo FS, 24d, $26,160 |
| GPU stack: vLLM, CUDA, drivers (AWS + dev cluster) | 0.5 d/mo ML, 6d, $7,680 | 1 d/mo ML, 12d, $15,360 |
| Model refresh: eval, regression, promote | 2 d/qtr ML, 8d, $10,240 | 3 d/qtr ML, 12d, $15,360 |
| Data pipeline: quarterly data.gov.au release | 2 d/qtr DE, 8d, $9,200 | 3 d/qtr DE, 12d, $13,800 |
| IaC, CI/CD, scheduler upkeep | 0.5 d/mo DE, 6d, $6,900 | 1 d/mo DE, 12d, $13,800 |
| RDS upgrades, backups, certs, DNS | 0.5 d/mo FS, 6d, $6,540 | 0.75 d/mo FS, 9d, $9,810 |
| Security: CVE triage, monitoring, SSP upkeep | 0.5 d/mo Sec, 6d, $13,800 | 1 d/mo Sec, 12d, $27,600 |
| Ops and on-call | 0.2 FTE, $41,400 | 0.2 FTE, $41,400 |
| Penetration test, annual | $18,000 | $18,000 |
| DR rehearsal, twice a year | 4d, $3,600 | 4d, $3,600 |
| Total | $130,440 | $184,890 |

Recommended: the full column, $185k a year. The lean column holds only while the FOI
load stays pilot-sized and the quarterly data release keeps landing clean.

Two notes. The uplifted dev cluster sits inside this line: it needs the same OS and
driver patches as the cloud boxes, plus its own haproxy and slurm units. And part of
this effort is fleet-shared: the author role, vLLM stack and security monitoring serve
Horizon too. If the swap and upkeep run once at fleet level, the FOI slice of the ML and
security lines drops. The table prices FOI carrying its own.

### 6.7 Bedrock as the alternative

Amazon Bedrock serves Llama 3.3 70B at $0.00072 per 1k tokens in and $0.00072 out. At
72M tokens a month that is AUD 72 a month, against $1,062 for the cheapest GPU instance.
Bedrock stays cheaper until roughly 3 to 5 billion tokens a month against committed GPU
pricing, and about 7 billion against on-demand. FOI usage today sits around 2% of that
crossover.

The trade is control and sovereignty. Self-hosting keeps weights, prompts and transcripts
off a third party inference service, matches the standing self-host principle, and
carries no per-token variability. The hybrid worth considering: self-hosted GPU in prod,
Bedrock as the failover lane for the chat path when the GPU is down. That adds about $1k
a year at current load.

### 6.8 Totals

Year 1 (build, uplift, then 9 months of prod on a 1 yr Instance SP):

| Line | Cost |
|---|---:|
| Implementation | $138,000 |
| Cluster uplift | $12,000 |
| AWS run: 3 months test only, then prod + test | $56,200 |
| AWS Business Support | $5,600 |
| Software licensing | $100 |
| Engineering support and operate, half year | $92,400 |
| **Year 1** | **$304,300** |

On-demand GPU instead of a Savings Plan adds about $27k. Year 1 range: $197k to $380k,
base case $304k.

Steady state, year 2 onwards:

| Line | Cost |
|---|---:|
| AWS run: prod + test, 1 yr Instance SP | $71,700 |
| AWS Business Support | $7,200 |
| Software licensing | $100 |
| Engineering support and operate, full year | $184,900 |
| **Annual** | **$263,900** |

Range: $154k (value GPU, lean engineering) to $304k (on-demand g5.12xlarge, full
engineering, paid observability). Base case $264k a year.

The Bedrock path for comparison: year 1 about $155k, steady state about $133k. It is
still the cheap option and the less sovereign one. The model above assumes the
self-hosted answer, which is what the uplift direction implies.

If this were quoted to a customer at cost plus 30% margin: year 1 about $395k, steady
state about $345k a year. The $185k engineering line is the cost basis behind whatever
support retainer gets offered with it.

### 6.9 Option E: two dedicated HA servers

Buy two identical servers and run the same pair the fleet already knows: box A prod
primary, box B prod standby that also carries test. haproxy floats the service address in
front of two vLLM backends, and Postgres streams from box A to box B. The static pages
render with the LLM down, so an LLM failover of minutes costs nothing visible.

Per box, standard tier:

| Part | Spec | Cost |
|---|---|---:|
| Chassis | 2U rack, dual PSU, rails | 3,500 |
| CPU + board | EPYC 7402 24 core, H12SSL | 1,300 |
| RAM | 256 GB ECC DDR4 | 1,700 |
| GPU | 2x A6000 48 GB used = 96 GB | 12,000 |
| Storage | 2x 4 TB NVMe mirror + 2x 8 TB SATA snapshots | 1,600 |
| Network + UPS share | 10 GbE NIC, 2200VA UPS share | 1,000 |
| **Per box** | | **21,100** |

96 GB per box runs Llama 3.3 70B FP8 with KV headroom, or AWQ with a lot of headroom. The
budget tier swaps the GPUs for 2x RTX 3090 (48 GB per box): same as the fleet today, 70B
AWQ with tight KV. Per box $11,700.

HA layout:

- Box A: prod app, Postgres primary, vLLM prod model.
- Box B: prod app standby, Postgres streaming replica, vLLM standby, test app and test model.
- haproxy or keepalived floats the service address. Postgres failover is manual or repmgr.

UPS honesty: a 2200VA unit rides roughly 20 to 40 minutes at this load. It covers brownouts
and short cuts, not site loss. Two boxes in one rack protect against hardware failure, not
against the building losing power or fibre. Site HA means box B in a second location:
colocation adds about $900 a month for 4U.

Capital, one-off:

| Line | Standard | Budget |
|---|---:|---:|
| Two servers | 42,200 | 23,400 |
| 10 GbE switch | 800 | 800 |
| Spares and install | 1,500 | 1,500 |
| **Total** | **44,500** | **25,700** |

Recurring, monthly:

| Line | Cost |
|---|---:|
| Power and cooling, both boxes | 450 |
| Offsite encrypted backup | 180 |
| **Total** | **630** |

Colocation for site HA: add about $900 a month. New hardware instead of used is 2 to 3
times these numbers. Used is the house pattern; the fleet is used 3090s.

What this option does to the totals, standard tier, idc-hosted:

- Year 1: implementation $138,000 + capital $44,500 + running $7,560 + engineering half
  year $92,400 + licensing $100 = **$283,000**. The AWS base case was $304,000.
- Steady state cash: running $7,560 + engineering $184,900 + licensing $100 = **$193,000**.
- Steady state TCO with a 3 yr hardware refresh: add $15,000 = **$208,000**. AWS base case
  $264,000, Bedrock path $133,000.
- Payback against AWS: about 10 months. AWS prod, test and support run $6,570 a month; the
  two boxes run $1,880 a month including amortisation. After payback the saving is about
  $56,000 a year.
- Quoted at cost plus 30% margin: year 1 about $368,000, steady state about $270,000 a year.

Two readings that matter. First, the hardware tier barely moves the total: budget GPUs
save only about $7,000 a year because the $185,000 engineering line dominates. Buy the
96 GB boxes or buy the 48 GB boxes, the people cost is the same. Second, the $12,000
cluster uplift from 6.3 drops: the two new boxes are the dedicated infrastructure, and
model evaluation runs on box B as test. Bedrock stays available as the failover lane for
about $1,000 a year if wanted.

### 6.10 Option F: AWS public front, on-prem inference

Split the app where it already splits. The 12 statistics pages are static once built,
and the app is designed to degrade honestly when the LLM or database is down. Host the
public site on AWS and keep the model, Postgres and lineage on the fleet.

Two ways to do the AWS side:

- H1: run the app on two t3.small instances across two AZs (ALB + WAF), Postgres and LLM
  reached over the tailnet. No code change, one env file. Pages render at boot under the
  same golden check.
- H2: pre-render the pages at deploy time and serve them from S3 behind CloudFront.
  Dynamic routes (/ask, /chat, /reports, /risk, /lineage) keep going through the existing
  Worker and tunnel to idc-1. Adds a render step to deploy. About $15 a month.

Monthly AWS, H1, AUD:

| Line | AUD |
|---|---:|
| 2x t3.small (2 AZ) | 54 |
| ALB + LCU | 60 |
| NAT gateway | 63 |
| WAF, logs, S3, secrets, KMS | 50 |
| Total | ~230 |

Business Support on a spend this small hits its minimum: USD 100 a month, about $1,700 a
year. H2 is about $15 a month and needs none of that.

On-prem side: the fleet as it stands (Llama 70B AWQ or Gemma 27B on the existing 48 GB
pairs) plus about $250 a month power and backup. The $12,000 uplift is optional. The two
HA boxes from Option E slot in unchanged.

Totals, H1, full engineering:

- Year 1: implementation about $134,000 (the landing zone shrinks to one account) plus
  uplift $12,000, AWS $2,760, support $1,700, on-prem run $3,000, engineering half year
  $92,400, licensing $100 = **$246,000**.
- Steady state: AWS $2,760 + support $1,700 + on-prem run $3,000 + engineering $184,900 +
  licensing $100 = **$192,000**. With the two HA boxes and their amortisation: **$212,000**.

What it buys and what it gives up:

- Public pages always up, two AZs, WAF, independent of on-prem power, GPU or link.
- Chat, builder and risk views depend on the on-prem link and box. They degrade honestly,
  which is the app's documented behaviour. /ask is the only public route that degrades.
- No RDS on AWS: sessions and chat history stay on-prem.
- Data: the pages carry published statistics only, OFFICIAL, fine on AWS Sydney, which is
  an IRAP-assessed region.

First sale on this shape: build $47,000 plus about $7,000 for the AWS front, run $38,000
over 6 months: **$92,000 internal, about $120,000 quoted**. Roughly $10,000 more than the
all-on-prem tight pilot, and it buys the public site being up even when the office is not.

Recommendation: H1 for the first sale (no code change, same golden boot), H2 once the
render step is worth $4,500 a year.

### 6.11 First sale price structure

The hybrid shape splits into three buyer-facing lines: config and install $70,000
quoted (internal $54,000), licence $30,000 a year (internal hosting basis $11,500 plus
product margin), support at pilot cadence $80,000 a year (internal $62,000). Year 1
$180,000 quoted, then $110,000 a year. Production-cadence support moves the support line
to $240,000 quoted; the licence stays $30,000. Licence plus support at $110,000 sits
inside the Horizon per-agency band of $50,000 to $180,000. Full table in the meeting
summary.

### 6.12 Build effort, sunk cost, and config on top

Measured from the repo, 2026-08-20 to 2026-08-28: 187 commits across 9 days, 18,711
lines of source and tests, 471 test functions, 26 task briefs, 30 task reports, 18 plan
and spec docs. Person-hours are not recorded; effort numbers are estimates.

Effort-equivalent build: about 30 person-days, range 25 to 35. About $35,000 at internal
derived rates, about $43,000 at charge-out rates. This is the FOI delta only; the
Horizon platform underneath is priced in the Horizon costings.

Charge the outcome, not the effort. The first sale returns about $34,500 of margin in
year 1 (licence margin plus config margin), which pays the $35,000 sunk build back
inside 12 to 18 months. If a buyer insists on a build line, quote $60,000 to $75,000.

Config on top of what we have done, at day rates (rates are the price): tech lead
$1,840, ML engineer $1,600, data engineer $1,440, full-stack $1,360, delivery lead
$1,520, security $2,880, support $1,120. Indicative packages: rebrand $3,000 to $4,000,
new data set ingest $4,000 to $7,000 per workbook, new page or report type $7,000 to
$11,000, extra environment $3,000. Options: Bedrock failover $1,300 a year, full pen
test $23,000, Cognito or Entra auth $7,000.

## 7. Open decisions

1. Measure the loaded day rate. Every estimate here scales with it. Horizon open item 8
   is still open.
2. Pick the model by benchmark. 70B AWQ on g5.12xlarge against Gemma 27B on g6.xlarge
   is a 4 to 5x swing in the prod run rate. Two weeks of evaluation decides it.
3. Commit timing. Run on-demand until load is proven, then take the 1 yr Instance SP
   (37% off g5, 35% off g6). The 3 yr (57% / 54%) needs conviction.
4. Whether the author role swap is fleet-wide. If Horizon and other products move off
   Qwen at the same time, the evaluation and regression cost is shared, and this model
   $19,720 line is the FOI slice of a bigger job.
5. Embeddings policy. FOI does not use them. If any FOI feature grows embedding
   retrieval, the horizon embedders are BAAI models and need a swap of their own
   (Snowflake Arctic or Jina).
6. Auth upgrade. Pilot PBKDF2 accounts or Cognito/Entra before prod. The hardening
   line assumes a modest Cognito integration.
7. IRAP and PROTECTED stay out. OFFICIAL on AWS Sydney is assumed. A PROTECTED
   deployment reprices the whole model and gets its own scope, same guard as Horizon.
8. Buy or rent. Two dedicated boxes pay back against AWS in about 10 months and land
   steady state near $208,000 TCO against $264,000 AWS and $133,000 Bedrock. Decide site
   HA up front: one rack is hardware HA only; a second site adds about $900 a month.
9. Public front. The AWS front plus on-prem inference lands steady state near $192,000 and
   keeps the public site up when the office is not. Pick H1 (two instances, no code
   change) or H2 (S3 and CloudFront, $15 a month, needs a render step).

## 8. Provenance

- FX: Wise mid-market 2026-08-28, 1 AUD = 0.7194 USD. Used 1.39 AUD per USD.
- EC2 and RDS prices: Holori calculators reading the AWS price list, ap-southeast-2,
  updated 2026-08-27/28. g6e absent from Sydney per the same source.
- Bedrock Llama 3.3 70B price: AWS Bedrock price list, $0.00072 in and out per 1k tokens.
  Verify the Sydney region before quoting.
- ALB, LCU, NAT, S3, gp3, CloudWatch, WAF, Support percentages: AWS list prices. The small
  lines are rounded and could move 10%.
- Day rates: Horizon cost model Assumptions sheet at 80%, per the derived-cost basis in
  the Parallax review. Unmeasured.
- Fleet and app facts: horizon SERVICES.md, fleet-platform-architecture.md,
  aws-migration-plan.md, bluebird-horizon-costing.md; this repo README and docs/deploy.md.
- On-prem server and GPU prices: Australian used market estimates. Get quotes before
  spending.
