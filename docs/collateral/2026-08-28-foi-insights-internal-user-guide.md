# FOI Insights: internal user guide

This guide covers the signed-in workspace: the Ask page and Risk & Forecast. It ends with the questions stakeholders will ask, and the answers.

## Signing in

Sign in with your pilot account (pilot01.user to pilot05.user). The login link sits top right. Signed-in users get the Workspace group in the left navigation: Ask, and Risk & Forecast. Public visitors do not see these. The public pages are identical for everyone.

## The Ask page

The Ask page is one box and one thread. Ask in plain English. The site decides what kind of answer to return:

- a figure: a KPI number or a table, computed from the published data, with the basis and the source rows and hash
- an explanation: where the question asks for something the data does not publish (for example a quarterly series), the site says so and offers the closest annual view
- provenance: where a figure or the data came from, file by file
- prose: a grounded answer with citations, for questions no fixed figure covers
- a dashboard: for requests that say "build a dashboard"

The model never writes a number. Every figure comes from the platform's own computation.

Questions that name specific agencies answer straight from the frame. "Compare Home Affairs and Services Australia" returns a table of both agencies across the two latest complete years. Misspelled questions still route correctly; the router tolerates typos.

### Building a dashboard

"Build a dashboard of requests received by agency" puts a job on the queue. The page shows the job card and its steps: queued, then each build turn, then the result. Each job gets two attempts. If both attempts fail, the site returns the closest computed figure for the same question, so a build never ends empty. The job card carries a Try again button.

Dashboards are saved per user. Only the account that asked for a dashboard can open it; the URLs are private, and the lineage transcript is private too.

### Your reports

The Your reports table sits below the thread. It lists each report with its status (queued, building, ready, failed), its creation time, and its latest step while it runs. Open a ready report, or delete any report you no longer want.

## Risk & Forecast

The page has two parts.

The forecast: the model's projection of request volume for the next three financial years, with a range. Below it, the top ten agencies by forecast volume.

The risk rating: a table of the reporting agencies, ranked by the share of decisions made within the statutory period in the latest complete year. The rating column is the model's expectation for the next year: low, medium or high risk. Click any row to see that agency's history and its own volume forecast. The table sorts by column, and filters by search text and rating. The forecast section's top ten table drills into the same detail.

The models were fitted on 27 August 2026 from the annual totals, with the time split on the financial-year boundary. The collapsed technical details block under each section names the model and the hash of the rows it was fitted on.

## Guardrails

The site answers questions about Australian Government FOI statistics only. A request outside that scope is refused, and the refusal names contact@bluebirdadvisory.com.au for anything the site cannot do. The model is the sovereign stack (fartkraft). It sees only the published data and the site's own figures. Generated answers follow the house style: short, plain Australian English, no padding.

## FAQ: questions stakeholders will ask

Where does the data come from?

The OAIC's FOI statistics dataset on data.gov.au. The site reads seven agency workbooks (2019-20 to 2024-25, plus the 2025-26 Q1 to Q3 file). Eight Q1 2025-26 headline figures were read from the OAIC's published dashboard. Every file is hashed, and the service refuses to start if a file changes without the registry changing.

Why does the latest year look lower than the one before?

The 2025-26 file is a part year (July to March). A part-year total is lower than a full year for that reason alone. The site labels it "part financial year" and never compares it with a full year without saying so.

Why is the received total different from the workbook total?

The workbook's "Total requests received" includes requests received on transfer from another agency. The site's headline counts requests received from applicants, and charts the transfer channel separately. For 2025-26 Q1 to Q3 the split is 34,418 from applicants and 392 on transfer, totalling 34,810.

Can we get quarterly or monthly numbers?

No. The source publishes annual financial years. The only finer data is the current year's Q1 headline figures and its Q1 to Q3 cumulative file. Quarterly or monthly series for earlier years do not exist in the published record.

What does a risk rating mean?

The rating is the model's expectation for the next financial year, computed from each agency's own history. The table ranks by the measured share of decisions made within the statutory period this year. Treat it as a planning signal about future timeliness.

How reliable are the forecasts?

They are model outputs, shown with a range. Agencies with short histories get flat, small forecasts. The site forecasts only agencies with enough annual history, and only years the source has published.

Why did a dashboard request return a table?

The build failed both attempts, so the site returned the computed figure for the same question. The job card shows the steps and a Try again button.

Are the reports private?

Yes. Each report belongs to the account that asked for it. The list, the dashboard URLs, the lineage pages and the build status all enforce ownership. A signed-in user from another account cannot open them.

What model powers the answers?

The sovereign stack (fartkraft). The model structures answers and drafts prose from the published data. It never writes a number: every figure comes from the platform's own computation, with a hash.

How often does the data refresh?

The annual files update when the OAIC publishes. The forecasts and risk ratings are re-fitted offline, and the page shows the fitted date. The rest of the site reads the files at boot.

Why does the site refuse some questions?

The scope guard allows Australian Government FOI statistics only. Anything else is refused and pointed to contact@bluebirdadvisory.com.au.

Who do I escalate to?

contact@bluebirdadvisory.com.au for anything the site cannot answer.

How do I correct something in the data?

Nothing on the site is edited by hand. A correction means correcting the published source file; the site picks it up on the next ingest. Raise it with the team rather than editing locally.
