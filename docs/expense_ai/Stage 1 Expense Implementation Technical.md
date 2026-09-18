MINTY  ·  PETTY CASH  ·  IMPLEMENTATION PLAN

Stage 1 on the Expense Page

How we implement the AI adoption Stage 1 plan on /report/expense, and which model to use

|  |  |
| --- | --- |
| Follows | AI adoption Stage 1 — Three Brains, three concepts, and the exclusion list |
| Page | /report/expense — the Add New Expense card |
| Approach | Vision-capable AI model. Explicitly not an OCR service. |
| Provider and route | Google Gemini, called through Google Cloud Vertex AI |
| Region | asia-southeast1 (Singapore) — the region the application already runs in. See 4.2. |
| Recommended model | Gemini 3.1 Pro (gemini-3.1-pro-preview) for the spike; newest GA Flash for production — see 4.3 |
| Fills | Expense Amount, Description, Suppliers, Account Code |
| Status | Draft for review — v3.1, 3 September 2026 |

## 1.  What this document does

The Stage 1 plan sets the architecture: three brains, a suggestion engine rather than an accounting engine, and a clear list of what we are not building. This document takes that plan and says exactly where each part lands on the expense page, and which model to call.

Two things in the plan do not have a home on the current form. Both are raised in section 9 rather than quietly dropped.

Version 2 of this document recommended Claude Opus 5 through the Anthropic API, which was set aside on availability grounds; Gemini has been the provider since version 3. What this version corrects is the reasoning about access, which was wrong in a way worth recording. Version 3 treated Hong Kong as the region our requests originate from and concluded that the direct developer APIs were closed to us. Hong Kong is where the team is. It is not where the code runs. The application servers are in Singapore, Google applies its regional restriction to the region of the calling instance rather than the user, and Singapore is on the supported list — so the developer API was open the whole time.

The provider does not change and the route does not change. Gemini through Vertex AI remains the recommendation. What changes is the reason — from “nothing else is available to us” to “this is the better of two available options” — and the region, which becomes asia-southeast1, where the application already runs.

| THE CORRECTED PICTURE IS THE BETTER ONE  Singapore's Vertex region carries a broad model catalogue, so the region no longer constrains the model choice; the residency story becomes one sentence rather than a trade-off; and a legal contracting question moves off the critical path. Sections 4.2, 4.3, 4.4, 6.2, 10 and 11 carry the change. Nothing in the feature design moves. |
| --- |

## 2.  The Three Brains, mapped to Minty

### 2.1  Brain 1 — AI Knowledge

The model receives the receipt and does two jobs, not one.

- Understanding the document — reads the document and returns supplier, amount and description.
- Applying business knowledge — recognises the vendor and knows what kind of expense it is. SF Express is courier. China Mobile is telephone. Hong Kong Electric is utilities. We do not teach it any of this.

The second job is the reason this cannot be an OCR service, and it is the whole argument of the Stage 1 plan. Section 3 covers what that rules out.

### 2.2  Brain 2 — Minty Context

Everything the model cannot know on its own, sent with the image on every request. All of it already exists in Minty for the dropdowns on the same form.

| Context | Source | Why the AI needs it |
| --- | --- | --- |
| Chart of accounts | The entity's synced Xero accounts | So it recommends 5100 Courier Expense rather than inventing a category. |
| Supplier list | The entity's synced Xero contacts | So a suggested supplier is one the user can actually select. |
| Entity information | Company name, country, currency | Improves recommendations and lets us flag a currency that does not match. |

| THIS IS THE WHOLE OF MINTY'S CONTRIBUTION IN STAGE 1  Context, not intelligence. We supply the lists and the company facts; the model supplies the judgement. Nothing here learns, ranks by history, or accumulates over time. |
| --- |

### 2.3  Brain 3 — User

The Add New Expense card is Brain 3. The plan's flow maps onto it exactly as written:

| AI Suggestion   ->   the four fields arrive prefilled and marked as suggestions User Reviews    ->   every field stays editable; low confidence is left blank User Confirms   ->   the user edits, tabs past, or presses Add Save            ->   Add submits exactly what it submits today |
| --- |

The user can accept, change or override completely. Nothing posts automatically, and the feature never appears on a submitted report.

## 3.  Why this is not OCR — and what that rules out

The plan is explicit that the goal is not Receipt → OCR → Done. That single line has a concrete procurement consequence worth stating, because the obvious candidates are OCR services and Minty already runs on AWS.

| Ruled out | What it does | Why it fails Stage 1 |
| --- | --- | --- |
| AWS Textract — AnalyzeExpense | Returns merchant, total and line items as typed fields | Extraction only. It can read “SF Express, HKD 120” but has no idea that means Courier Expense, and cannot choose from our chart of accounts. |
| Google Document AI | Same class of receipt parser | Same reason. Note this is not the same product as Gemini on Vertex AI, despite both being Google Cloud: Document AI is the parser we are ruling out; Gemini is the model we are choosing. |
| Azure Document Intelligence | Same class of receipt parser | Same reason. |
| Tesseract / PaddleOCR | Raw text only | Everything after the text is a parser we would write and maintain. No business knowledge at all. |

All four cover Brain 1's first job and none of them cover the second. A vision-capable AI model does both in one call, which is why the plan points there.

## 4.  Which model

### 4.1  What Stage 1 actually requires of the model

- Vision. Reads an image or a PDF — the upload accepts both.
- Business knowledge. Knows Hong Kong vendors. SF Express, PARKnSHOP, China Mobile, Hong Kong Electric.
- Structured output. Returns JSON reliably, not prose. This is Concept 1 of the plan.
- Constrained selection. Picks from a supplied list rather than generating a value.
- Multilingual. Many HK receipts are Traditional Chinese or mixed script.
- Callable from where our code runs, on terms we can accept for customer documents. Gemini clears both halves; the second half is what decides the route, and it is the subject of 4.2 and 4.3.

### 4.2  Where we call from, and what that opens

Our servers are in Singapore. That single fact decides what is available to us, and it is the fact an earlier draft of this document got wrong. Google states plainly that its regional restrictions are applied on the region of the calling instance, not the region of the user — and Singapore is on the supported list.

| Route | Open to our Singapore servers? | Detail |
| --- | --- | --- |
| Google Cloud Vertex AI, asia-southeast1 | Yes — chosen | Enterprise Google Cloud terms, an in-region endpoint with a published ML-processing residency commitment, IAM instead of an API key, and a broad in-region model catalogue spanning several publishers. |
| Gemini API direct (ai.google.dev) | Yes | Singapore is a supported region. Genuinely viable and faster to start, but with the data-handling limits set out in 4.3. Suitable for a spike on non-customer receipts; not for customer documents. |
| Amazon Bedrock, Microsoft Foundry | Yes | Under AWS and Azure terms respectively. Fallbacks — see 4.4. |

| THE CHOICE IS A REAL ONE  Two Google routes are open to us and we are picking between them on merit, not taking the only one left. Section 4.3 says which, why, and when the other is the right tool. One rule carries over regardless: we do not reach a restricted endpoint through a VPN, a proxy, or a third-party API reseller. Nothing in this plan requires it, and nothing in a future revision should. |
| --- |

One general lesson, recorded so it is not re-learned: when checking whether a service is available, check it from where the code runs, not from a browser on someone's desk. The two answers differ, and the second is not the one that matters.

### 4.3  Recommendation

| USE GEMINI THROUGH GOOGLE CLOUD VERTEX AI, IN ASIA-SOUTHEAST1 (SINGAPORE)  The same region the application already runs in. Customer receipts already live in Singapore, so a Singapore regional endpoint means this feature moves no customer data across a border it does not already cross — which is the whole compliance conversation, answered in one sentence. |
| --- |

Four further reasons for Vertex over the direct Gemini API.

- The direct API cannot make that promise. Even on the paid tier, Google's Gemini API terms reserve the right to store or cache data in any country in which Google or its agents maintain facilities. There is no regional endpoint to pin. For a bookkeeping product holding clients' financial documents that is a real gap, not a technicality.
- No long-lived API key. Vertex authenticates with IAM, and workload identity federation from our AWS role means there is no secret to leak, rotate, or accidentally commit.
- Co-located with the application. Same region, lowest latency, on a path where a user is watching a form.
- The region does not constrain the model. asia-southeast1 carries a broad catalogue across Google, Anthropic, Alibaba, OpenAI and others, so model choice and region choice are independent here.

When the direct Gemini API is the right tool: it is legitimately faster to start, being an API key and one dependency with no project, IAM or federation work. Use it only on the paid tier — the free tier's terms let Google use submitted content to provide, improve and develop its products, and let human reviewers read, annotate and process API input and output, which is categorically unacceptable for a customer receipt. Use it only with non-customer receipts, ours or synthetic. Both tiers use the same SDK and the same code, so the difference is invisible at the call site and entirely visible in the terms. Moving to Vertex afterwards changes the client constructor, not the call.

One caveat remains. gemini-3.1-pro-preview is a preview model: preview releases change behaviour, can be retired at short notice, and are frequently excluded from enterprise availability and support commitments. It is the right instrument for measuring the accuracy ceiling in a throwaway spike, and it must not be the production pin. If the spike shows that only Pro clears the bar, wait for the GA release or re-open 4.4. Confirming which models asia-southeast1 serves today is still the first task of stage 0, but as a routine check rather than a risk.

Pricing is per million tokens. The spike runs on the strongest candidate so the accuracy number is a ceiling rather than a compromise; stepping down then becomes an informed decision instead of a hopeful one.

| Model | Model ID | Input / 1M | Output / 1M | Note |
| --- | --- | --- | --- | --- |
| Gemini 3.1 Pro (preview) | gemini-3.1-pro-preview | $2.00 | $12.00 | Spike here. Highest accuracy. Preview — see the caveat above. |
| Gemini 3.8 Flash | gemini-3.8-flash | $0.75 | $3.75 | Likely production choice. Promotional rate through 31 December 2026. |
| Gemini 3.5 Flash | gemini-3.5-flash | $1.50 | $9.00 | Stable, non-promotional Flash pricing. Budget at this rate. |
| Gemini 2.5 Flash | gemini-2.5-flash | $0.30 | $2.50 | Cheapest credible option. Older; test vendor knowledge before assuming. |
| Gemini 3.5 Flash-Lite | gemini-3.5-flash-lite | $0.30 | $2.50 | Cheapest tier. Likely too weak for the business-knowledge half of Brain 1. |

*Three warnings attached to that table. These are Google's Gemini API list prices, checked on 3 September 2026 — Vertex AI publishes its own price list and the rates are not guaranteed to match, so re-verify there before committing a budget. The Flash promotional rate expires on 31 December 2026, so a cost model built on $0.75 / $3.75 will be wrong in January; budget at the Gemini 3.5 Flash rate and treat the promotion as upside. And preview-model pricing is not a commitment.*

### 4.4  Alternatives to Gemini

Gemini is the decision and none of the following is being built alongside it. This is a procurement fallback list, kept so that a commercial or capability setback costs a provider swap rather than a restart. On the corrected facts every entry is reachable from Singapore, so the list is genuinely available rather than theoretical.

| Alternative | Case for | Case against, and the verdict |
| --- | --- | --- |
| Claude via Vertex AI Model Garden | Same Google Cloud project, billing account, credentials and region as Gemini, and Google lists Claude among the models with in-region ML processing in asia-southeast1. A switch would be a model string and a request shape inside one module. | Nothing structural against it — it is simply not the chosen provider. Verdict: the strongest fallback, and an argument for the Vertex route in its own right, because choosing Vertex buys this option for free. |
| Claude via Amazon Bedrock | Claude under AWS terms, and Minty's application database already runs on AWS, so the commercial relationship exists. | A second AI vendor relationship when the option above needs none, and narrower regional coverage for the newest Claude models. Verdict: keep on the list; the Model Garden route is strictly easier for us. |
| GPT-5.x via Microsoft Foundry / Azure OpenAI | Strong vision and structured output, with an APAC Data Zone for regional processing. | A third cloud vendor to onboard, with new identity, billing and network plumbing and no existing adjacency. Verdict: the fallback if both Google routes fail. |
| Qwen3-VL via Alibaba Cloud Model Studio (Singapore endpoint) | The strongest native handling of Traditional and Simplified Chinese in this list, roughly an order of magnitude cheaper than Gemini Flash, and on a Singapore endpoint that matches where our data already sits. A free evaluation quota makes a comparison arm nearly free. | The blocker is governance, not technology: sending clients' financial documents to a PRC-headquartered vendor is a decision for the business and for our clients, and may be unacceptable to some regardless of where the endpoint sits. Verdict: do not adopt without an explicit business decision, but include it in the spike as a comparison arm and put the numbers to the business alongside the governance question. |

To be plain — this is a procurement fallback list, not a runtime design. Section 8 still excludes multi-provider routing, and 4.5 still holds.

### 4.5  One provider, no routing

The plan rules out multi-provider AI routing, and 4.4 must not be read as licence to build a provider abstraction. We take that literally: one provider, one model, one function that makes the call. No fallback chain, no provider abstraction layer, no runtime model selection. Keeping the call in a single module is enough to make a future change cheap without building the routing the plan excludes — and the change of provider between versions 2 and 3 is the evidence that this is the right call, because the provider changed completely and the change was confined to one section of this document and would be confined to one module of the codebase.

## 5.  The three concepts, implemented

### 5.1  Concept 1 — Structured output

The reply is a fixed JSON shape, enforced by the API rather than requested politely in the prompt. A schema is supplied with the request and the model cannot return anything else.

| { "supplier":    { "contact_id": "...", "name": "SF Express",     "confidence": 0.93 }, "account":     { "account_id": "...", "code": "5100", "name": "Courier Expense",                     "confidence": 0.88 }, "amount":      { "value": 120.00,                               "confidence": 0.97 }, "description": { "value": "Courier delivery",                   "confidence": 0.81 }, "currency":    "HKD" } |
| --- |

Any field the model cannot read comes back empty rather than guessed. Supplier and account are returned as ids from the lists we supplied, and Minty re-checks that before the reply reaches the page. Define the schema once as a Pydantic model, pass model_json_schema() on the request and parse the reply with model_validate_json(). Do not put the chart of accounts into the schema as an enum: it would make the schema large enough to risk rejection, it re-sends on every call, and it invalidates the cached prefix on every Xero sync. The accounts go in the prompt context; constrained selection is enforced by Minty's own id check, which is required regardless.

### 5.2  Concept 2 — Confidence

Every field carries its own confidence, because one receipt can have a crisp total and an illegible supplier. The plan's examples set the shape of the rule: 95% is good, 55% needs review.

| Confidence | Behaviour on the card |
| --- | --- |
| High | Field is prefilled and marked as a suggestion. |
| Medium | Field is prefilled and marked more strongly for review. |
| Low | Nothing is prefilled. A wrong suggestion costs the user more than no suggestion. |

The exact cut-offs come from spike data, not from a guess made now. Confidence is self-reported by the model — a useful signal, not a measured probability — and that is as true of Gemini as it was of Claude. The spike must report accuracy per confidence band per field, and the cut-offs are set from that table.

### 5.3  Concept 3 — Suggestion engine, not accounting engine

The accounting logic stays in Minty. Concretely, the model never touches any of these:

- Validating that a suggested account is real — Minty re-checks it against the entity's list.
- Creating a supplier. If there is no match the field is left empty and the user uses the existing New Contact panel.
- The expense total, the closing balance, or any figure on the report.
- Anything to do with publishing to Xero.
- Deciding whether the expense is valid. Add validates exactly as it does today.

## 6.  How it works on the page

### 6.1  The flow

| 1  user attaches receipt on the Add New Expense card        (unchanged) 2  browser calls  POST /report/expense/extract              (new) 3  server loads the entity's accounts, contacts, currency   (Brain 2) 4  server calls the model: image + context + JSON schema    (Brain 1) 5  server validates ids against the lists it sent 6  four fields arrive on the card, marked as suggestions    (Brain 3) 7  user checks, adjusts if needed, presses Add              (unchanged) |
| --- |

| STEP 7 IS UNTOUCHED  Reading the receipt happens beside the form, never inside Add. If the model is slow, rate limited or down, the card behaves exactly as it does today and the user types the four fields. Expense entry can never be blocked by an outage. |
| --- |

### 6.2  The request

The receipt and the Minty context go in one call, against the asia-southeast1 Vertex AI regional endpoint. The stable part — instruction, entity facts, chart of accounts, supplier list — goes first, because Gemini caching is implicit prefix matching and there is no cache marker to set.

| from google import genai client = genai.Client( vertexai=True,                            # IAM, not an API key — see 4.3 project=settings.GOOGLE_CLOUD_PROJECT, location=settings.EXPENSE_AI_LOCATION,    # "asia-southeast1" http_options={"timeout": 25_000},         # milliseconds ) interaction = client.interactions.create( model=settings.EXPENSE_AI_MODEL, input=[ # stable prefix FIRST — this is what implicit caching matches on {"type": "text", "text": INSTRUCTION + entity_context + chart_of_accounts + supplier_list}, {"type": "document", "data": base64_bytes, "mime_type": "application/pdf"},     # or image/jpeg, image/png {"type": "text", "text": "Extract the four fields."}, ], response_format={ "type": "text", "mime_type": "application/json", "schema": ExpenseSuggestion.model_json_schema(),   # the schema from 5.1 }, generation_config={"thinking_level": "low", "max_output_tokens": 1024}, ) suggestion = ExpenseSuggestion.model_validate_json(interaction.output_text) |
| --- |

*The SDK is google-genai (pip install -U google-genai). Do not start from google-generativeai or from vertexai.generative_models — both are deprecated, and most examples still in circulation use them. The direct Gemini API uses the same package and the same call; only the client constructor differs, taking an api_key instead of the Vertex arguments above. That is what makes the fallback in 4.3 cheap, and also what makes it easy to end up on the wrong route by accident — so if both are ever configurable, make Vertex the default and the API-key path an explicit opt-in.*

PDFs are read natively, up to 50 MB or 1,000 pages, billed at a flat 258 tokens per page; images go in the same way with the mime type changed, so no conversion step is needed either way. Run the existing downsize_bytes helper first: Gemini rescales pages to a maximum of 3072 x 3072, so sending more resolution than that is pure waste.

Caching works differently from the version 2 design, and the cost model depends on it. The interactions API supports implicit caching only — there is no cache_control marker to set. A hit requires the stable content to come first and to stay byte-identical, which is why the lists must be sorted deterministically. The minimum cacheable prefix is 4,096 tokens on Gemini 3.x, so a small entity's chart of accounts may never produce a hit — and no error is raised when it does not. Verify with usage.total_cached_tokens during the spike. Note also that the Vertex global endpoint supports neither caching nor the residency commitment, which is why we call a regional endpoint.

### 6.3  What the user sees

| State | When | On screen |
| --- | --- | --- |
| Reading | Receipt attached, model working | A quiet indicator on the upload area. All fields stay editable. |
| Suggested | Value returned with enough confidence | Field filled and marked as a suggestion, with a one-tap clear. |
| Confirmed | User edits, tabs past, or presses Add | Becomes an ordinary value; the marking disappears. |
| Blank | Low confidence or unreadable | Field left empty. The user fills it as they do today. |
| Unavailable | Model slow or down | No indicator, no error. The card is exactly as it is now. |

| NEVER OVERWRITE THE USER  If a field already holds a value when the reply arrives — because the user typed faster than the model — that field is left alone regardless of confidence. |
| --- |

## 7.  What it costs

A rough per-receipt estimate, to be replaced with a measured figure at the end of the spike. Assumes one receipt plus the entity context in, a short JSON reply out, and no cache hit — the pessimistic case.

|  | Tokens | Gemini 3.1 Pro | Gemini 3.5 Flash |
| --- | --- | --- | --- |
| Input — receipt + context | ~5,000 | ~$0.010 | ~$0.008 |
| Output — JSON reply | ~300 | ~$0.004 | ~$0.003 |
| Per receipt |  | ~$0.014 | ~$0.011 |

For comparison, the version 2 estimate on Claude Opus 5 was about $0.03 per receipt, so the provider change is cost-neutral at worst. Cost was never the reason for the change and should not be presented as the justification for it. Budget at the Gemini 3.5 Flash column: the newer Flash models are cheaper still, but only on a promotional rate that ends on 31 December 2026. Implicit caching lowers the input side within a data-entry session, subject to the conditions in 6.2, and a PDF costs a flat 258 tokens per page — which makes the multi-page question in section 11 a cost question as well as a correctness one. At petty-cash volumes the total is likely to be small, but the spike should produce a real number before anyone commits to it.

## 8.  What we are not building

Taken directly from the Stage 1 plan. Listed here because two of them were in earlier Minty drafts and are now removed.

| Excluded | Consequence for this build |
| --- | --- |
| Complex entity learning engine | No learning of any kind in Stage 1. |
| Historical behaviour engine | The account-code ranking from past expenses that appeared in the earlier Minty proposal is dropped. The model's own business knowledge replaces it. |
| Multi-provider AI routing | One provider, one model, one call. No fallback chain or abstraction layer. The alternatives in 4.4 are a procurement fallback list, not a runtime design. |
| AI orchestration platform | A single request. No pipeline, no queue, no agent loop. |
| Custom accounting intelligence system | Minty supplies context and validates the result. It does not reason about accounting. |

The duplicate-receipt check from the earlier Minty proposal is also out of scope here. It is not part of Stage 1 and should be considered separately.

## 9.  Two things the plan needs a decision on

The Stage 1 plan lists five things for the AI to extract. Two of them have nowhere to go on the current form. Flagging rather than assuming.

### 9.1  Date

The plan has the AI extract the date, and the worked example includes 28 Aug 2026. The Add New Expense card has no date field — an expense takes its date from the report being worked on, shown in the page header.

Three options, in order of preference:

1. Extract and check. The model returns the date, and Minty uses it only to warn when the receipt is from a noticeably different day than the report. Nothing new appears on the form.
1. Extract and hold. The model returns it, we store it, nothing uses it yet.
1. Skip. Do not ask for it in Stage 1.

### 9.2  Invoice number

Same situation — the plan lists it, the form has no field for it. It could be appended to Description, or held for a later stage. Adding a field to the form is a bigger change than this feature should carry on its own.

| NEITHER OF THESE BLOCKS THE WORK  Both can be settled after the spike, when we know how reliably the model reads them off real receipts. Extract-and-check is the safe default for the date in the meantime. |
| --- |

## 10.  Delivery

| Stage | Work | Outcome |
| --- | --- | --- |
| 0 — Access | Google Cloud project and billing, Vertex AI enabled, a service account with roles/aiplatform.user and federated credentials from AWS, and confirmation of which models asia-southeast1 serves today. One successful call from the application's own network path — not from a laptop. | A working credential and a confirmed model id. Half a day. |
| 1 — Spike | A throwaway script, a batch of real Hong Kong receipts, and a per-field accuracy report. Run on Gemini 3.1 Pro via Vertex, then re-run on the intended production Flash model so the step-down decision has both numbers. Optionally add Qwen3-VL as a comparison arm on Chinese-language receipts. No page changes. | A go / no-go, plus the real cost per receipt and the confidence cut-offs. |
| 2 — Server | The extract endpoint: Brain 2 context assembly, the model call, schema enforcement, and id validation. | Extraction working and testable, nothing visible to users. |
| 3 — Page | Suggestion states on the Add New Expense card, wired into the upload that already exists. | Live behind a flag for one pilot entity. |
| 4 — Measure | Accept rate per field. | Evidence for which fields keep the feature. |

| STAGE 0 IS SMALLER THAN IT LOOKED, AND STILL WORTH IT  An earlier draft made this stage existential because it believed access was blocked. On the corrected facts it is routine setup. It stays because the lesson holds: verify from where the code runs, and find out in half a day rather than in stage 2. |
| --- |

| STAGE 1 OF DELIVERY IS NOT OPTIONAL  Whether the model reads real Hong Kong receipts accurately is the single assumption the whole plan rests on, and it can be tested in isolation for very little. Building the page first would mean finding out last. |
| --- |

## 11.  Open questions

1. Google Cloud retention posture. Confirm in writing that customer content is not used to train foundation models and is not retained beyond abuse detection. Blocks pilot.
1. Preview-model dependency. If only gemini-3.1-pro-preview clears the accuracy bar, we have no production-safe model and must either wait for GA or re-open 4.4.
1. Cost ceiling. What is acceptable per receipt at expected daily volume — and re-baselined for the January 2027 end of promotional Flash pricing?
1. Date and invoice number — the two decisions in section 9.
1. Confidence cut-offs. Set from spike data; self-reported confidence is not a calibrated probability.
1. Traditional Chinese receipts. How common in the real mix, and does Gemini handle them well enough? The Qwen comparison arm in the spike would quantify what we are giving up.
1. Multi-page PDFs. The upload accepts PDF. Which page do we read? At 258 tokens per page this is a cost question as well as a correctness one.
1. Cache hit rate may be low — implicit-only caching with a 4,096-token minimum prefix. Entities with small charts of accounts may never get a hit. Cost only.
1. Customer disclosure wording. What we tell clients about receipts being processed by Google in Singapore. Expected to be straightforward given that the data already resides there, but it still needs agreeing.

Two questions that blocked pilot in the previous draft no longer appear: whether we could reach the provider at all, and which jurisdiction would process the data. Both are answered by Singapore. Google Cloud contracting is now ordinary procurement rather than a risk.

Minty · Petty Cash · Stage 1 on the Expense Page · v3.1 · Gemini on Google Cloud Vertex AI, asia-southeast1 · Draft for review
