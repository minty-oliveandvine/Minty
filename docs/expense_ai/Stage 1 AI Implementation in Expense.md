High-Level Feature Documentation

1. Context & Objective

- Proposed Solution: We are introducing an AI receipt pre-filling feature powered by a vision model Google Gemini, called through Google Cloud Vertex AI in the Singapore region. As soon as a user attaches a receipt, the system reads the image, applies business context, and automatically pre-fills the form fields as suggestions, leaving the user to simply verify and save.
- Business Impact: Speeds up daily expense entry by shifting the user's role from manual data entry to quick verification.
- Provider Note: The first version of this plan named Claude, which was set aside on availability grounds; Gemini is the provider. This version also corrects the access analysis in the version before it, which assumed our requests originate in Hong Kong. They originate in Singapore, where our servers run. Section 5 sets out what that means. The feature design itself is unchanged throughout.

2. Scope & Boundaries

- In Scope (Goals):
  - Smart Pre-Filling: Automatically populating four core fields upon receipt attachment: Expense Amount, Date, Description, Supplier, and Account Code.
  - Constrained Matching: Feeding our existing supplier directory and chart of accounts into the AI model so its suggestions strictly match valid dropdown options.
  - Intuitive Suggestion States: Clear visual cues that distinguish AI suggestions from user-typed text, easy one-tap clearing, and strict rules to never overwrite what a user has already typed.
  - Non-Blocking Fallback: Running the AI read asynchronously in the background, keeping the form fully editable even if the model is slow or unavailable.
- Out of Scope (Non-Goals):
  - Historical Learning & Ranking Engines: No complex entity learning engines, historical behavior tracking, or past expense account ranking systems.
  - Multi-Provider AI Routing: No multi-provider fallback chains, abstraction layers, or complex agent orchestration pipelines.
  - Auto-Creating Contacts: The AI will never automatically create a new supplier if a match is not found.
  - Auto-Submission: The system will never automatically save or submit an expense without the user explicitly clicking "Add".

3. Narrative User & System Journey

- Phase 1: Initiation & Context Assembly → The user attaches a receipt on the expense card. The app sends the receipt alongside the entity’s active suppliers and chart of accounts to the server endpoint.
- Phase 2: Execution & Vision Reading → In the background, the server calls the vision engine to analyze the receipt against the provided context and returns structured predictions with confidence scores.
- Phase 3: Completion & Confirmation → The card pre-fills empty fields with clearly tagged "Suggested" values. The user reviews or edits the fields (which instantly converts them to normal text) and clicks "Add" to save.

4. Core Components & Responsibilities

| Component / Module | High-Level Role | Key Dependencies |
| --- | --- | --- |
| Expense Entry Form (/report/expense) | Captures uploaded receipts, displays temporary suggestions, and handles user edits or submission. | Web Frontend, Existing Dropdowns |
| Extraction Endpoint (POST /report/expense/extract) | Assembles entity context, invokes the AI vision model with enforced schemas, and validates returned IDs. | Web Backend, Entity Data Services |
| Vision AI Model (Gemini) | Reads document images or PDFs, applies business knowledge to classify vendors, and returns structured predictions. | Google Cloud Vertex AI (asia-southeast1) |
| Context Integration Service | Pulls the entity's active suppliers and chart of accounts to send along with the receipt, preventing invalid options. | Contacts API, Chart of Accounts API |

5. Model Access & Data Handling

- Where We Call From: Our servers are in Singapore, and Google applies its regional restrictions to the region of the calling instance rather than the region of the user. Singapore is on the supported list, so both of Google's routes are open to us — the direct Gemini API and Google Cloud Vertex AI. An earlier draft of this document assumed our calls originated in Hong Kong and concluded that neither was available. That was wrong, and correcting it turns a forced decision into a real choice.
- The Route We Chose: Google Cloud Vertex AI, on the asia-southeast1 (Singapore) regional endpoint — the same region the application already runs in. Customer receipts already live in Singapore, so this feature moves no customer data across a border it does not already cross. That is the whole compliance conversation, answered in one sentence.

| Route | Availability to us | What it means |
| --- | --- | --- |
| Google Cloud Vertex AI, asia-southeast1 | Available — chosen | Enterprise Google Cloud terms, an in-region endpoint with a published ML-processing residency commitment, IAM instead of a long-lived API key, and a broad in-region model catalogue. |
| Gemini API direct, paid tier | Available, not chosen | Viable and faster to start, but there is no regional endpoint to pin: even on the paid tier the terms allow data to be cached in any country where Google maintains facilities. Suitable for a prototype on non-customer receipts only. |
| Gemini API direct, free tier | Available, and not usable | Submitted content is used to improve Google products, and human reviewers may read API input and output. Never acceptable for a customer receipt. Both tiers use identical code, so this difference is invisible to a developer and entirely visible in the terms. |
| Amazon Bedrock / Microsoft Foundry | Available — fallbacks | The same reasoning under AWS and Azure terms. See section 7. |

- One Rule, And One Lesson: We will not use a VPN, a proxy, or a third-party API reseller to reach a restricted endpoint — it breaches the provider's terms and would route customer financial documents through an unvetted intermediary. Nothing in this plan requires it. And the lesson from the correction above, recorded so it is not re-learned: check whether a service is available from where the code runs, not from a browser on someone's desk.

6. Model Suggestions

| Model | Model ID | Input / 1M | Output / 1M | Note |
| --- | --- | --- | --- | --- |
| Gemini 3.1 Pro (preview) | gemini-3.1-pro-preview | $2.00 | $12.00 | Run the prototype here to establish the accuracy ceiling. Preview releases must not be pinned in production. |
| Gemini 3.8 Flash | gemini-3.8-flash | $0.75 | $3.75 | Likely production choice. Promotional rate through 31 December 2026 only. |
| Gemini 3.5 Flash | gemini-3.5-flash | $1.50 | $9.00 | Stable, non-promotional Flash pricing. Budget at this rate. |
| Gemini 2.5 Flash | gemini-2.5-flash | $0.30 | $2.50 | Cheapest credible option. Older; test vendor knowledge before assuming. |
| Gemini 3.5 Flash-Lite | gemini-3.5-flash-lite | $0.30 | $2.50 | Cheapest tier. Likely too weak for the business-knowledge half of the task. |

- 1 Million Input Tokens is roughly equivalent to processing 200 separate receipt uploads (at ~5,000 input tokens each)
- 1 Million Output Tokens is equivalent to generating about 3,300 JSON replies (at ~300 output tokens each).

7. Alternatives Considered

- One Provider, One Model: The exclusion on multi-provider routing still stands and nothing below is being built alongside Gemini. This is a procurement fallback list, kept so that a commercial or capability setback costs a provider swap rather than a restart. All of these are reachable from Singapore, so the list is genuinely available rather than theoretical.

| Alternative | Why it is on the list | Why it is not the choice |
| --- | --- | --- |
| Claude via Vertex AI Model Garden | The same Google Cloud project, billing account, credentials and region as Gemini, and Google lists Claude among the models with in-region processing in Singapore. A switch would touch one module. | Nothing structural — it is simply not the chosen provider. This is the strongest fallback, and an argument for the Vertex route in its own right: choosing Vertex buys the option for free. |
| Claude via Amazon Bedrock | Claude under AWS terms, and Minty's application database already runs on AWS. | A second AI vendor relationship when the option above needs none, and narrower regional coverage for the newest models. Keep on the list; Model Garden is easier for us. |
| GPT-5.x via Microsoft Foundry / Azure OpenAI | Strong vision and structured output, with an APAC Data Zone for regional processing. | A third cloud vendor to onboard, with no existing adjacency. The fallback if both Google routes fail. |
| Qwen3-VL via Alibaba Cloud (Singapore) | The strongest Traditional Chinese handling of the options, roughly an order of magnitude cheaper, and on a Singapore endpoint that matches where our data already sits. | Sending clients' financial documents to a PRC-headquartered vendor is a business and client decision, not an engineering one. Recommended as a measurement in the prototype, not as an adoption. |

8. Operational & Strategic Constraints

- Performance & Scale Expectations: Receipt processing must happen quietly in the background without freezing the UI. Calling an endpoint in the same region as the application keeps latency low. Caching should be used to lower input token volume, but note that Gemini caches implicitly rather than on an explicit marker: the benefit only arrives when the entity context is sent first and kept identical between receipts, and it should be measured rather than assumed.
- Security & Compliance: Customer receipts contain sensitive financial data, and they already reside in Singapore. We will call the Vertex AI asia-southeast1 regional endpoint rather than the global one, so that model inference happens in the same jurisdiction, and confirm in writing that customer content is neither retained beyond abuse detection nor used to train foundation models. The region setting is a compliance control, not a performance knob, and should be documented as such.
- Key Risks & Mitigations:
  - ***Risk:* A user accepts a wrong amount or account code without double-checking.

***Mitigation:* Keep suggested fields visually distinct, enforce strict confidence thresholds before showing a suggestion, and require manual submission.

  - ***Risk:* AI provider outage halts expense entry.

***Mitigation:* Keep the AI process completely decoupled from form submission so the card works normally for manual entry if the AI is offline.

  - ***Risk:* API costs scaling unpredictably with high volume.

***Mitigation: Send the entity context first and unchanged so implicit caching can take effect, establish per-receipt cost baselines during prototype benchmarking, and budget at the standard Flash rate — the cheapest rates quoted in section 6 are promotional and end on 31 December 2026.*

- Risk: A developer reaches for the quick path and sends customer receipts through the direct Gemini API — or worse, its free tier, whose terms permit human review of submitted content.
- Mitigation: Make Vertex the only configured route, keep no Gemini API key in configuration at all so its presence is itself the alarm, and state the tier distinction plainly in the runbook. Both routes use identical code, so this cannot be caught by code review alone.
- Risk: The strongest model is a preview release, or is not served in the region we choose.
- Mitigation: Confirm the region's model list before any code depends on a model id  half a day of setup at the start of the work and ship on a generally-available model. A preview release is acceptable for the prototype only, never for a customer path.
