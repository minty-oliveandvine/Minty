-- ===========================================================================
-- pettycash_test :: the redesign, REBASED ONTO HEAD (new prestaging database)
--
-- Derived from `01_schema 2.sql`, which is kept unmodified beside this file.
-- Do not edit both: this one is the working schema, that one is the record of
-- what was originally designed.
--
-- ---------------------------------------------------------------------------
-- WHY THIS EXISTS
--
-- `01_schema 2.sql` was written against alembic revision e5b7d9f1a3c6 - nine
-- revisions along the CURRENCY branch of the migration graph, before that branch
-- merges with the sales/cash/report work. It is not wrong; it is nine revisions
-- behind. Almost everything it appears to "drop" simply did not exist yet.
--
-- This file brings it forward to head (z1a01_drop_payer_cycle) 
-- without giving up any of its modelling.
--
-- ---------------------------------------------------------------------------
-- WHAT WAS ADDED
--
--   59 tables + 2 views     618 columns                21 enums
--   88 foreign keys         147 indexes                34 updated_at triggers
--   0 double precision      0 naive timestamp
--
-- Every one of those is MEASURED off a build of this file, not counted by hand -
-- the query is at the end of HOW TO BUILD IT. Re-measured 2026-09-15 after item
-- 18 (enum vocabulary, user.system_role restored, the tracker view carried
-- across). The previous header carried two different foreign-key counts (104
-- here, 87 further down) and two different enum counts, which is what happens
-- when they are maintained by arithmetic.
--
-- 14 TABLES - the 13 subscription/billing tables plus entity_cash_setting. Each
-- declares a model and is referenced by 3-23 files; all arrive at revision
-- a1b2c3d4e5f7, long after this design's source. Without them, subscriptions,
-- Stripe billing and terms consent are offline.
--
-- 27 COLUMNS - split three ways after checking each against the dead-column audit:
--
--   restored, live      user.reset_token / reset_token_expiry (NULL is the
--                       RESTING state of a working flow, not death), and 23
--                       others added after e5b7d9f1a3c6
--
--   restored, then       entities.period_lock_date / end_of_year_lock_date. The
--   dropped again        rebase brought them back on a count of 13 code refs
--                        each; the 2026-09-09 pass read those refs and found
--                        every one of them is a WRITE. See ERA 3 item 15.
--
--   left dropped, dead  entities.minimum_qty / deposit_frequency / deposit_day /
--                       xero_short_code and user.xero_token - model declaration
--                       only, no reader, no writer, NULL in all three databases
--
--   left dropped, dead  the 8 auth_* / django_* tables. Zero models, zero code
--                       references, five entirely empty
--
-- ---------------------------------------------------------------------------
-- DECISION REGISTER
--
-- Three eras, oldest first. The register used to begin at the rebase, which made
-- the design look as though it started there; most of what this schema IS was
-- settled before that, and two of those earlier decisions explain findings that
-- otherwise read as mistakes.
--
--   ERA 1  the uuid7 branch          superseded, kept for its reasoning
--   ERA 2  the 01_schema 2 redesign  inherited; six principles, two reversed
--   ERA 3  the rebase                items 1-16, this file's own decisions
--
-- ---------------------------------------------------------------------------
-- ERA 1 - THE uuid7 BRANCH.  SUPERSEDED, AND RECORDED BECAUSE IT WAS.
--
-- Its schema survives as docs/schema/archive/pettycash_test_v2_schema.sql
-- (the working files were deleted on 2026-09-17). It was a different answer
-- to the same question and it was dropped, but its constraints have not gone
-- away.
--
--   A1. uuid v7 - TIME-ORDERED - as the default on every primary key, and built
--       from pgcrypto primitives rather than the native uuidv7(). PostgreSQL 18
--       has uuidv7(); SUPABASE RUNS 17.6 AND DOES NOT, and pg_uuidv7 is not
--       among the extensions Supabase offers - only pgcrypto and uuid-ossp. The
--       finished schema has to restore onto Supabase, so the function was built
--       by hand. That constraint still holds for anything that later wants v7.
--
--   A2. The function was duplicated into pettycash_test rather than shared with
--       the migration schema, so that `pg_dump --schema=pettycash_test` carries
--       its defaults instead of depending on a schema meant to be thrown away.
--
--   A3. 67 tables preserved one-for-one. No consolidation.
--
--   A4. The defect register carried as 152 COMMENT ON statements, so the schema
--       and its documentation could not drift apart.
--
--   A5. Indexes and constraints applied AFTER the load: an index maintained
--       during a bulk insert costs more than one built at the end, and the
--       foreign keys double as the migration's acceptance test.
--
--   SUPERSEDED BY "adopt the 01 schema, use the uuid from 01 schema":
--   gen_random_uuid() - v4, NOT time-ordered - and consolidated tables instead
--   of 67 preserved ones. A1's Supabase reasoning is the part worth keeping.
--
-- ---------------------------------------------------------------------------
-- ERA 2 - THE 01_schema 2 REDESIGN.  INHERITED.
--
-- These are the load-bearing decisions: they are why the schema has the shape it
-- has, and two of them account for findings that look like defects until you
-- know the principle behind them. They existed only as Korean comments in
-- `01_schema 2.sql` under 주요 재설계 원칙 (DBA), based on
-- prestaging_table_08_jul_2026.sql and targeting PostgreSQL 14+.
--
--   B1. DROP THE draft/v2 TABLES.  report / report_draft / report_v2 collapse
--       into one `report` with a status state machine; report_cashcount_draft
--       into report_cash_count with the denominations normalised;
--       shop_expense_draft into report_expense; report_history_* into
--       report_history.
--
--   B2. NORMALISE THE SALES CHANNELS.  report's ~18 *_sales columns become
--       sale_info + report_sale.
--       >> This is why report.shop_sales and report.delivery_sales have no
--          column here. They are not lost: the per-method breakdown lives in
--          report_sale joined to sale_info.type, and nocashsale_total is the
--          roll-up. Readers sum rather than read a column.
--
--   B3. STANDARDISE THE TYPES.  varchar(36) -> uuid, double precision on money
--       -> numeric, timestamp -> timestamptz, status strings -> enum.
--       >> Every one of the 170 type findings in APPLICATION_CHANGES.md comes
--          from here. The numeric ones are the only bugs among them: a model
--          still declaring Float reintroduces exactly the money rounding this
--          principle was adopted to remove.
--
--   B4. SEPARATE THE TOKENS.  user (identity) -> app_user + user_token, the
--       OAuth pair 1:1. This is where User's six token columns went.
--
--   B5. FIX THE TYPOS.  "desc", sync_statuc, xero_reponse_text,
--       xero_organiztion_id.
--
--   B6. LEAVE THE DJANGO FRAMEWORK TABLES ALONE.  auth_*, django_*, sessions
--       stay with framework migrations; identity and permissions consolidate
--       into the custom role / permission / user tables.
--
--   TWO OF ERA 2's OWN DECISIONS WERE REVERSED INSIDE THE SAME FILE. Recorded so
--   they read as choices rather than inconsistencies:
--
--     * app_user -> user.  B4 named the table app_user; the file ships `user`,
--       because the source left app_user commented out while the foreign keys
--       referenced it.
--     * entity_role kept as the app's existing SIX-LEVEL hierarchy (ROLE_RANK in
--       services/permission_policy.py) rather than the redesign's
--       owner/admin/member/viewer, so user_entity.role and invitation.role
--       migrate without a lossy remap.
--
-- ---------------------------------------------------------------------------
-- ERA 3 - THE REBASE.  THIS FILE'S OWN DECISIONS.
--
-- Items 1-4 were taken while rebasing. Items 5-10 were taken 2026-09-04, after a
-- sweep that compared every enum and every foreign key against what the four
-- repos actually declare - not against what the data happens to hold today. That
-- distinction is the whole point: a survey of the data finds the values in use,
-- an enum has to cover the values the code can PRODUCE, and those are not the
-- same set.
--
-- Items 11-16 were taken 2026-09-09, at schema review. They are the first ones
-- that REMOVE things rather than widen them, and the same distinction decides
-- them from the other side: a column is dead when nothing READS it, which a
-- reference count cannot tell you and only reading the references can. Two of
-- the six columns removed here were kept by an earlier item on a count that
-- turned out to be counting writers.
--
-- 1. ENUMS ONLY FOR VOCABULARIES WE OWN. subscription_phase, extension_state,
--    transfer_status and audit_outcome come verbatim from
--    blueprints/subscription/constants.py. subscription_invoice.status and
--    subscription_email_log.status stay VARCHAR because they mirror Stripe's
--    vocabulary - an enum over someone else's value set fails closed the day
--    they add a value. Same line this file already draws for the Xero ids.
--
-- 2. SECTION K MONEY IS INTEGER CENTS, not NUMERIC like the rest of the schema.
--    Those amounts come from and go to Stripe, whose API is integer minor units;
--    converting would mean rounding at every boundary for no gain.
--
-- 3. report_expense.files / s3_key were TRANSITIONAL. DISCHARGED BY ITEM 11 -
--    the migration those columns were waiting for now exists, so they are gone
--    and the paths are attachment rows. Kept here because the condition it set
--    is the reason the columns survived three earlier passes.
--
-- 4. fk_user_current_entity was an ALTER after `entities`, not inline, because
--    user and entities referenced each other and one of the two keys has to come
--    later whichever order the tables are declared in. SUPERSEDED BY ITEM 14:
--    user.current_entity_id is dropped, so there is no cycle and no deferred
--    ALTER. `entities` still points at `user` three times; nothing points back.
--
--
-- 5. ENUMS WERE WIDENED TO WHAT THE CODE WRITES. REVERSED BY ITEM 18.
--
--    Taken 2026-09-04: nine of the thirteen enum-backed columns held production
--    values their enum rejected, because the enums had been INFERRED from a
--    sample of the data rather than read from the writers. The answer then was
--    to widen every enum to the union of both vocabularies so the load could not
--    lose a row, and to schedule the narrowing for later.
--
--    Kept in the register because the observation is still true and still
--    matters: an enum has to cover what the code can PRODUCE, and a data survey
--    cannot see that. Item 18 answers it the other way round - the vocabulary
--    is fixed here, and the code is what changes.
--
-- 6. attachment_role BECOMES TWO ENUMS.  bill_attachment and payment_attachment
--    use two different vocabularies that share only 'other'. Detail in the note
--    above the declarations.
--
-- 7. THE SERVICE BOUNDARY CARRIES NO DATABASE-LEVEL INTEGRITY.
--
--    16 foreign keys running from billing-backend's tables into Minty's (user,
--    entities, currency_info, xero_contact_sync) were dropped:
--
--      attachment.uploaded_by            bill.contact_id
--      bill.created_by                   bill.currency_id
--      bill.entity_id                    bill_attachment.created_by
--      bill_audit.user_id                entity_bill_account_xero.created_by
--      entity_bill_account_xero.entity_id
--      entity_bill_currency.created_by   entity_bill_currency.currency_id
--      entity_bill_currency.entity_id    payment.created_by
--      payment.currency_id               payment_attachment.created_by
--      xero_bill_sync.requested_by
--
--    None of them existed. Not one is a Django relation - every column above is
--    a CharField or UUIDField, and the models that do point at Minty tables
--    (shared_models/models.py) are `managed = False` read-only mirrors. Asked
--    directly, production enforces TEN foreign keys on these tables and all ten
--    stay inside billing-backend: bill, attachment, payment, xero_bill_sync.
--    Zero cross the boundary.
--
--    Six of the sixteen had unloadable data behind them - 973 rows on
--    entity_bill_account_xero.created_by alone, whose values include blanks and
--    the string '10-23-4-6'.
--
--    The cost is real and should be stated: nothing at the database level now
--    stops a bill from naming an entity that does not exist. That is the
--    existing contract between the two services, not a regression introduced
--    here, and re-adding any one of these is a one-line ALTER once the owning
--    service is ready to guarantee it.
--
-- 8. THE md5-DERIVED USER IDS STAY AS THEY ARE.
--
--    user.id is VARCHAR(36) at head and two of the 119 rows are not uuid-shaped
--    - '10-23-4-6' and '10-21-128-8', both live accounts. The loader converts
--    them with md5('user:'||id)::uuid, which is deterministic, so 02 and 03
--    agree without sharing state.
--
--    Those two values are well-formed 128-bit uuids but not RFC 9562 version-4
--    ones; the version and variant nibbles are whatever the hash produced.
--    Nothing reads them. Forcing the bits would mean changing all 24 call sites
--    in 02 plus every one in 03 in the same commit, and determinism - not
--    conformance - is the property this migration actually depends on.
--    Check B6 in 02 proves both accounts and all their references survive.
--
-- 9. entity_status AND invitation_status WERE WIDENED, NOT CONSOLIDATED.
--    SUPERSEDED BY ITEM 18, which consolidates them on the way in: active and
--    cancelled -> disconnected (measured: none of the nine ever submitted a
--    report or a bill), invitation cancelled -> revoked. The code sites that
--    write the old names are listed there.
--
-- 10. THE DATABASE IS AUTHORITATIVE; THE APPLICATION FOLLOWS IT.
--
--     Stated here because it decides the cases above and the ones still to come.
--     Where the schema and the code disagree, the schema is not automatically
--     wrong. Changing the code is a legitimate outcome, scheduled as work rather
--     than treated as a constraint that forces the column's hand.
--
--     Applied first to entity_function_map.created_by. It had been retyped to
--     VARCHAR(36) on 2026-09-04 because modules.py:534 writes an actor label
--     there. That is backwards: this design named the column a creator
--     reference, so it stays UUID with fk_efm_creator, and modules.py changes.
--     Nothing converts - the column is NULL in every source row.
--
--     It does NOT license changing a column the code is right about. Decision 5
--     went the other way on the same day: sale_type is Capitalised because
--     onboarding_state.py:166 filters on the literal, and rewriting four repos
--     to suit an enum's spelling buys nothing. The test is which side is
--     actually the better model, not which side is easier to edit.
--
-- 11. EXPENSE RECEIPTS BECOME ROWS.  report_expense loses item_code,
--     attachment_id, files and s3_key; report_expense_attachment arrives.
--
--     attachment_id could never have worked. 1049 of the 10235 populated `files`
--     values are a COMMA-SEPARATED LIST, so the model this schema declared -
--     one expense, one attachment - would have silently kept the first receipt
--     of each expense and dropped the rest. The link table is not a refinement
--     of that design; it is the design that matches the data.
--
--     item_code goes with them for a different reason - it is a Xero item code
--     on a petty-cash expense line, backfilled from the account when absent
--     (report/routes/api.py:375-394), and account_id already carries the
--     posting. It is the one column of the four with live writers, so it is the
--     one whose removal is a genuine feature decision rather than a cleanup.
--
--     report.receipt_files is dropped in the same spirit and with less doubt: it
--     had four readers, NO WRITER anywhere in blueprints/, and is NULL in all
--     three databases. It was the report-level twin of this same problem, never
--     wired up.
--
-- 12. A TOTAL DOES NOT GET A COLUMN.  report.actual_cash_total is replaced by
--     the view report_cash_summary(report_id, actual_cash_total, cash_balance),
--     and report_cash_count gains the cash_value it should always have had.
--
--     The column was written in one place from the LIVE cash_info values
--     (report/routes/cash_count.py:273-286, :361) while every reader of the same
--     quantity summed the SNAPSHOTTED value on the count row instead
--     (get_cash_count_total, cash_denominations.py:163-182). Two derivations of
--     one number, agreeing only because both ran inside the same request. The
--     view leaves one, and the snapshot wins because it is the revaluation-proof
--     one - head's model has said so since r10a10
--     (report/models/report_cash_count.py:36-38); the rebase simply never
--     carried the column across.
--
--     NULL IS PART OF THE CONTRACT. save_cash_count_details deletes the row for
--     a denomination counted as zero, so "counted, all zero" and "never counted"
--     both have no rows - and the app distinguishes them precisely by
--     actual_cash_total IS NULL (ending.py:651, :1290). A view built on an inner
--     join, or on COALESCE(...,0), would collapse the two and quietly mark every
--     uncounted report as counted. The LEFT JOIN is load-bearing.
--
-- 13. cash_addition_type, NOT withdrawal_type.  The column records whether money
--     ADDED to the float came from the company or from someone personally -
--     'personal' / 'company', validated at report/routes/api.py:1200-1201 - and
--     it now sits beside cash_addition, which is the figure it qualifies.
--     Nothing about it was ever a withdrawal.
--
--     withdrawal_bank_account goes entirely: the account actually used is the one
--     configured on entity_pettycash_settings, and a per-report override that
--     nothing reconciles against that configuration is a second source of truth
--     for the same fact.
--
-- 14. user.current_entity_id IS DROPPED, AND THIS ONE HAS A KNOWN COST.
--
--     Unlike the other removals in this pass the column is NOT dead. It is read
--     at services/user_presence.py:115 and written at :164, :176, :195, :204 and
--     :253, and auth/models/user.py:67-81 records what it is for: without it "a
--     person signed in to company A was listed as present in company B", because
--     nothing else in the row says WHICH company they are in.
--
--     It is removed on instruction, and the cost is stated rather than hidden:
--     until user_presence.py is rewritten, Settings > Users answers "who is
--     signed in to Minty" where it used to answer "who is here, in this
--     company". signed_in_at and last_seen_at are both facts about the person,
--     so neither can take over the question.
--
--     Decision 10 covers this - the schema is allowed to win and the code is
--     scheduled to follow. It is recorded at length because a later reader
--     finding a removed column with six live references should be able to tell a
--     decision from an accident.
--
-- 15. THE XERO LOCK DATES ARE NOT STORED; THE RULE IS ENFORCED INSTEAD.
--
--     entities.period_lock_date and end_of_year_lock_date are dropped. Item 33
--     of the rebase had restored them on a count of "13 code references each" -
--     but reading those references rather than counting them, every one is a
--     WRITE. backfill_lock_dates_if_needed (entity/services/settings.py:968-992)
--     fetches them from Xero and stores them; the two call sites
--     (entity/routes/settings.py:1099, settings.py:1446) exist only to trigger
--     that fetch when they are NULL. NOTHING IN MINTY EVER READS THEM. No report
--     path consults them, no template shows them.
--
--     Worse, the guard is fill-only, so a lock date moved in Xero is never
--     picked up and the stored value silently rots.
--
--     The replacement is behaviour, not storage: editing data before the
--     published lock date raises an error the user sees, checked against Xero at
--     the moment it matters. get_organisation_lock_dates
--     (xero/services/integration.py:142-198) already fetches them and needs no
--     new scope.
--
--     THE COST CROSSES A SERVICE BOUNDARY, so state it. billing-backend mirrors
--     both columns (shared_models/models.py:52-53) and DOES read them:
--     bills/services/xero_publish_service.py:369-379 forces an invoice dated on
--     or before a lock date to DRAFT. That mirror is `managed = False`, so it
--     selects every declared field and breaks the moment these columns go.
--     Removing the two fields there and moving that guard to the same live fetch
--     is part of this change, not a follow-up someone may skip.
--
-- 16. financial_year_end_day / financial_year_end_month ARE ADDED.
--
--     Neither exists anywhere in either repo today - zero hits for
--     financial_year, fiscal, year_end in Minty and in billing-backend. They are
--     new, required during onboarding, and refreshed when a Xero connection is
--     established.
--
--     The refresh is nearly free and that is the point: Xero's Organisation
--     response carries FinancialYearEndDay and FinancialYearEndMonth, we already
--     fetch that exact object at xero/services/integration.py:170 under a scope
--     we already hold, and lines 189-190 read the two lock dates out of it and
--     throw the rest away. Item 15 stops reading that object for the wrong
--     fields; this one starts reading it for the right ones.
--
--     Nullable, for the same reason country_code and currency_id are: an entity
--     mid-onboarding has not reached the step yet. CHECK constraints bound them
--     to 1-31 and 1-12 rather than a DATE, because a financial year end is a
--     recurring day-of-year, not a date.
--
-- 17. THE BILLING ACCOUNT IS THE IDENTITY, AND IT HOLDS THE CARDS.
--     Taken 2026-09-10. THIS ONE LEADS THE CODE - see the note under WHAT WAS
--     ADDED. No migration has been written yet; the schema is carrying the
--     decision first because the onboarding design that forced it is signed off.
--
--     Onboarding's card dialog (Figma 01-D) asks for an EMAIL and a BILLING
--     COMPANY before the card fields, and nothing in either repo stored either.
--     The Stripe customer carries an email, but _payer_identity() overwrites it
--     from the user record on every write, and the customer's name is the
--     payer's human name by an explicit earlier decision - an entity name there
--     "would be wrong the moment a second entity is added".
--
--     So the identity goes where the money already is. payer_billing_group was
--     already "one payment method, plus everything it pays for"; entities point
--     at it, and the cycle and the dunning clock live on it. Adding
--     billing_email / billing_company makes it the account the payer creates and
--     recognises, with no new join on any billing query.
--
--     A PAYER MAY HOLD SEVERAL ACCOUNTS, AND AN ACCOUNT SEVERAL CARDS. That is
--     what costs uq_payer_billing_group_payer_card (2.46) and what
--     billing_account_payment_method (2.47) exists for. The account still
--     charges ONE card - the id stays on the account row so renewals and dunning
--     never join to find it - and the shelf records the rest.
--
--     WHAT THIS CHANGES BENEATH: paid_through, dunning_started_at and
--     dunning_attempts were per CARD when a group was a card. They are now per
--     ACCOUNT. The grain is unchanged in practice, because one invoice is raised
--     per group either way, but the reason has moved and the docstring on the
--     model says the old one.
--
--     NOT DONE HERE, AND OWED: the identity is only true if it reaches Stripe,
--     which means _payer_identity's "our record is the source of truth" rule has
--     to yield to the account's own fields where they are set. That is an
--     application decision, and it is recorded there rather than here.
--
-- 18. THE ENUMS RETURN TO THE REDESIGN'S VOCABULARY; THE DATA IS MAPPED.
--     Taken 2026-09-15, after the review the previous section of this header
--     used to ask for ("DECISIONS REQUIRED AT REVIEW - SIX OPEN"). All six are
--     closed, and the widening of item 5 is reversed.
--
--     D1-D5 turned out to be artefacts of the two-hop pipeline: production
--     holds 'posted', 'shortage'/'surplus', 'Electronic'/'Delivery',
--     'cancelled' and all five entity states; the 'published'/'none'/'electric'
--     /'revoked'/'onboarding' variants were introduced by the schema-2 hop's
--     own mappings. The pipeline is now ONE hop (pettycashv2 at head ->
--     this schema), so there is no lossy intermediate to argue about.
--
--     That left one question, and it was answered the redesign's way: the
--     members are `01_schema 2.sql`'s, production data is mapped onto them by
--     the loaders, and the application changes to write them in a later pass.
--     The mapping lives in ONE place - generators/gen.py ENUM_MAP - and is
--     what generates 02, 03, the B3/R3 count assertions and 00. Each
--     declaration below carries the measured counts. In summary:
--
--       entity_status      active 7, cancelled 2         -> disconnected
--       system_role        superuser 1 -> superadmin, user 1 -> normal
--       invitation_status  cancelled 40                   -> revoked
--       report_status      posted 4886 -> published 4046 / submitted 790 (loaded;
--                          derived, see below)
--       publish_status     completed 3851, NULL/'' 1051, failed 11, partially_published 3
--                          -> completed 4046 / failed 14 / unpublished 801 (derived
--                          from the same fact as report_status, see below)
--       module_code        BILL 1                         -> PAYMENT_REQUEST (item 20)
--       discrepancy_type   surplus 188 -> over, shortage 272 -> short, NULL -> none
--       sale_type          Electronic -> electronic, Delivery -> delivery, Cash -> other
--       bill_status        voided 26                      -> void
--       publish_state      not_published 96               -> draft
--       sync_direction     outbound 470                   -> push
--       entity_role        'shop manager' 1               -> shop_manager
--
--     Two members that schema 2 did not have were KEPT because they are live
--     workflow states, not spellings: bill_status.returned (submitted ->
--     returned -> submitted | void, bills/api.py:431-485; 2 open bills) and
--     publish_state.failed (set on every Xero push error, drives the retry
--     action; 2 rows). Members with no writer anywhere were dropped whatever
--     the model class declares: bill_status authorised / cancelled /
--     sync_failed, payment_status cancelled / refunded, sync_status partial,
--     sync_direction inbound, report_status partially_published.
--
--     sale_type is spelled 'electronic'; schema 2's 'electric' was a
--     misspelling and item 5's Capitalised pair was the code's.
--
--     D6 is closed by uncommenting user.system_role. The global super admin
--     is mintyliveadmin@dailyminty.com (superuser -> superadmin); the second
--     non-normal row, minty.jp1@oliveandvinehk.com, holds the pre-split value
--     'user' and loads as normal.
--
--     THE CODE THAT NOW DISAGREES WITH THIS FILE, for the pass that follows:
--     the 'superuser' constant (Minty auth/system_roles.py:6,
--     services/permission_policy.py:26, admin_list.py:97, two templates;
--     billing-backend core/auth.py:61,132,226, core/views.py:34;
--     onboarding-backend core/policy.py:42 - it rides in the JWT claim, so all
--     three change together); 'posted' (ending.py:483,1568,
--     history_query.py:90) - and publish.py:2495 must ALSO set
--     status = 'published' where it sets xero_integrated today, or every report
--     published after cutover stays 'submitted' while the loaded ones say
--     'published' (report_history.html:513 can then read status instead of the
--     flag); 'shortage'/'surplus' (cash_count.py:322);
--     'Electronic'/'Delivery' (onboarding_state.py:166 and 45 more sites plus
--     five templates); invitation 'cancelled' (invite.py:421); entity
--     'active'/'cancelled'/'deleted' (create.py:1219, entity.py:33,
--     xero/routes.py:1067, list.py:486); 'partially_published' (publish.py:2514)
--     and 'processing' (submitted.py:301) -> 'publishing'; and in billing-backend
--     the TextChoices classes in bills/models.py ('voided' -> 'void',
--     'not_published' -> 'draft' including the model default at :45 and the
--     frontend union type in BillActionBar.tsx:18, plus the dead members).
--
-- 19. WHAT THE LOAD ADDS, DROPS AND COLLAPSES. Measured by scripts/schema_migration/
--     rehearse.py on the 2026-08 production dump (2026-09-15) and again on the
--     2026-09-16 dump; the numbers below are the 09-16 ones, August in brackets
--     where they moved. rehearse.py writes the full list with ids to
--     backups/<db>_not_carried.md on every run and FAILS if any of these numbers
--     moves. Nothing here is silent.
--
--     DROPPED, counted (decision: drop and count, not resurrect):
--       55 reports (43 of them posted) naming 5 entities that no longer exist,
--          with their 444 sale rows, 278 cash-count rows, 99 expenses and 5
--          history rows; 10 entity_function_map rows on the same entities.
--       43 reports that were a SECOND row for the same entity and day - the
--          abandoned report_v2 drafts r-series folded in beside the real posted
--          report (none has an expense or a cash count). The posted row wins;
--          between drafts, the one with a count, then more expenses, then later.
--          report is UNIQUE (entity_id, transaction_date) here, as designed.
--       28 (29) users whose Xero tokens sat only on the user table (May 2026, before
--          user_token existed) - every refresh token past its 60-day life.
--       sessions (Flask-Session), alembic_version, the auth_* / django_* tables.
--
--     COLLAPSED, every reference remapped to the survivor:
--       sale_info 65 -> 40 (57 -> 35): the per-entity CUSTOM_* rows that repeat a name
--          (Payme x13, JCB x9) fold onto one catalogue row per exact name, the
--          global row where there is one. entity_sale_setting and report_sale
--          point at the survivor. sale_info is UNIQUE (sale_name) here.
--
--     ADDED, because the data still named them:
--       238 (239) xero_contact_sync rows (category 'restored') and 10 (7) account_info rows
--          (description 'restored by the schema migration ...'). shop_expense
--          holds XERO ids, not internal ones; the FKs here want the internal
--          row; 947 expense lines named contacts and 368 named accounts the sync
--          tables no longer held. The contacts were deleted by the mass-delete
--          bug fixed 2026-07-23 (commit 5229231, tests/
--          test_xero_contact_sync_no_mass_delete.py); the accounts were
--          archived or renumbered in Xero. Rebuilt from contact_name /
--          account_code, which the expense row kept. No expense lost a link.
--       277 (184) report_cash_count rows of quantity 0. Item 12 replaced
--          report.actual_cash_total with a view that is NULL when a report has
--          no count rows - but the app stores no row for a zero count, so the
--          284 (190) posted reports counted as ALL ZERO would have read as never
--          counted. One inert zero row each keeps the 0. The other 7 are Test_1
--          (PHP) and BIB GROUP (no currency set), which have no denominations
--          at all; they read NULL.
--
--     MAPPED, found by the 09-16 dump: report.publishing_status
--       'partially_published' (3 posted Test_1 reports, no bank transactions) ->
--       'failed', the state the app reads it together with (history_query.py:102);
--       202 reports published before publishing_status existed (2026-01-12 ..
--       04-19: NULL there, flag set, 'published' history row) -> 'completed',
--       not 'unpublished' - and their status -> 'published' (item 18);
--       user_entity.role 'Admin' (1 row) -> admin - both role columns are
--       lower-cased and snake-cased, as the app's normalize_role does.
--
--     TRANSLATED:
--       report.uploaded_by (a username) -> created_by (the user's id).
--       one report_sale_detail id, 202608171300, is not uuid-shaped -> md5, as
--          any non-uuid key is.
--       cash_info.cash_id (serial) and report_history.id (serial) -> uuid via
--          md5, the same way the two legacy user ids are (item 8).
--       report.nocashsale_total = total_sales - cash_sales: shop_sales INCLUDES
--          cash (shop = cash + electronic; total = shop + delivery), measured on
--          3,748 of 3,847 reports. 6 draft reports have columns that disagree
--          with their own detail rows in the source; carried as they are.
--       report.created_at = date, or transaction_date where date is NULL (2).
--
-- 20. THE MODULE CODE 'BILL' IS 'PAYMENT_REQUEST'. Taken 2026-09-16.
--     entity_function.function_code names Minty's two modules. The second one
--     has always been the Payment Request module - its function_name says so -
--     and the code now says so too: PETTY_CASH and PAYMENT_REQUEST. The three
--     function_code columns (entity_function, entity_module_subscription,
--     subscription_audit_log) are the enum module_code, so after cutover the
--     writers listed below are REJECTED, not merely wrong. The loader maps the
--     value (gen.py ENUM_MAP); the tracker view filters on the new name.
--     entity_function_map is untouched - it references the row by id. "Super
--     Minty" is the billing_plan bundle row (BILL+PETTY_CASH), not a module.
--
--     NOT renamed, by decision: billing_plan.code stays 'BILL', 'PETTY_CASH',
--     'BILL+PETTY_CASH'. The plan key is derived in code as the sorted join of
--     the module codes (blueprints/subscription/models/billing_plan.py:12-14),
--     which will produce 'PAYMENT_REQUEST+PETTY_CASH' once the code follows -
--     so the plan lookup needs a mapping in the code pass. The payment-request
--     app's own tables (bill, bill_line, bill_audit ...) and enums keep their
--     names.
--
--     THE CODE THAT NOW DISAGREES, for the pass that follows: Minty
--     MODULE_BILL = "BILL" (blueprints/subscription/models/billing_plan.py:41,
--     blueprints/entity/services/modules.py:18) and ~50 references in 12 files
--     - entity/routes/create.py, modules.py, settings.py, subscription/
--     services/notify.py, portal.py, scripts/e2e_seed.py, replay_scenarios.py,
--     seed_past_due.py, seed_transfer_demo.py, preview_billing_emails.py -
--     including the JWT module claims; billing-backend core/entitlements.py (the
--     payment-request app's module gate) and bills/tests/test_deactivate_account
--     .py; onboarding-backend onboarding/services/plans.py, shared_models/
--     models.py, tests/; onboarding lib/api.ts (type ModuleCode) and
--     e2e/xeroFake.ts; billing-frontend's module claims.
--
-- 21. country_info HAS NO updated_at TRIGGER. Found 2026-09-16 in C3, decided
--     2026-09-17. The table sat in the updated_at trigger list (section 3)
--     without the column, so every UPDATE on it failed with 'record "new" has
--     no field "updated_at"' (onboarding-backend's Postgres-mode tests hit it).
--     country_info is seeded once and only read - no application code updates
--     it - so it does not get the stamps; its name comes out of the trigger
--     array instead. currency_info keeps its stamps: the source schema had them.
--
-- 22. xero_report_sync AND xero_bank_transfer CARRY created_at / updated_at.
--     Decided 2026-09-17. Both are rewritten in place when a report is
--     republished and nothing recorded when; the source schema had no stamps
--     there either. Both join the updated_at trigger list. On load the loader
--     fills them from the truthful dates rather than the cutover moment:
--     xero_report_sync.created_at <- reported_at, updated_at <- completed_at
--     (then reported_at, then now()); xero_bank_transfer <- transfer_date.
--
-- 23. subscription_invoice_line RECORDS WHAT EACH LINE PAID FOR. Decided
--     2026-09-25. period_start / period_end / unit_amount, all NULL-able. A line
--     held only its amount, kind and `at`, so the payer portal's billing breakdown
--     (08-B "Download csv", a row per company per line) had to work each line's
--     days and monthly rate back out of how that kind is priced - and could not,
--     for an access extension, once a resume had cleared the module's
--     app_access_until. Both billing engines (Minty's subscription services and
--     minty-billing-api) now write all three when an invoice is issued; the
--     breakdown reads them and derives only where they are NULL (every line issued
--     before, and the rate of an extension priced at more than one rate). No load
--     change: pettycashv2 has no such columns and 03 leaves them NULL. pettycashv3
--     only; a database already up gets the guarded ALTER in migration
--     x1a01_invoice_line_span.
--
-- ---------------------------------------------------------------------------
-- HOW TO BUILD IT
--
--     psql "$URL" -v ON_ERROR_STOP=1 -f docs/schema/01_schema_rebased.sql
--
-- Builds clean on an empty database: 59 tables, 2 views, 623 columns, 22 enums,
-- 88 foreign keys (measured 2026-09-25 at 620 columns and 22 enums before item 23
-- added its three columns - the line had still read 618 / 21). Every __tablename__ in Minty (44) and every db_table in
-- billing-backend (22) resolves to a table here, the nine renames included.
--
-- Then it is FILLED, in this order:
--
--   00_enum_coverage_check.sql          read-only; proves every mapped value lands
--   02_data_foundation_rebased.sql      foundation tables from pettycashv2 at HEAD
--   03_data_reports_rebased.sql         reports and billing; needs 02 committed
--
-- ONE HOP. The source is pettycashv2 at alembic head, in the same database,
-- and the loaders are generated from information_schema
-- by generators/gen.py. The redesign's own hard parts - the report/draft/v2
-- merge, the sales normalisation, the cash-count rows - are done by the
-- application's alembic chain (r1a01..r10a10, s1a01..s5a05, c1a01/c2a02) on the
-- way to head, which joins on the shared primary key rather than guessing a
-- winner by (entity, date). scripts/schema_migration/rehearse.py runs the whole
-- thing - restore, snapshot, upgrade, upgrade check, build, 00, 02, 03 - and
-- exits non-zero on any check. The schema-2 hop and its loaders are in
-- docs/schema/archive/.
--
-- The counts in this file are measured, never estimated:
--
--   SELECT (SELECT count(*) FROM information_schema.tables
--            WHERE table_schema='pettycash_test' AND table_type='BASE TABLE') AS tables,
--          (SELECT count(*) FROM information_schema.views
--            WHERE table_schema='pettycash_test') AS views,
--          (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
--            WHERE n.nspname='pettycash_test' AND t.typtype='e') AS enums,
--          (SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
--            WHERE n.nspname='pettycash_test' AND c.contype='f') AS fkeys;
--
-- ---------------------------------------------------------------------------
-- WHAT THIS BREAKS IN THE APPLICATION
--
-- APPLICATION_CHANGES.md, beside this file, lists every model in Minty and
-- billing-backend that this schema no longer fits, with file and line. It is
-- generated by generators/audit_models.py -> mkdoc.py, so REGENERATE it rather
-- than editing it, and re-run it after any change here. The counts below come
-- from that regeneration and are not maintained by hand.
--
--   tables renamed out from under a model    (invitations -> invitation,
--        shop_expense -> report_expense, report_sale_detail -> report_sale, ...)
--   model columns this schema does not have  - these break every SELECT on the
--        model, not just writes, because an ORM selects all mapped columns
--   declared types that no longer match. Only the `numeric` ones are a bug
--        rather than untidiness: a model still declaring Float reintroduces the
--        money rounding this schema moved to numeric to remove.
--
-- THE 2026-09-09 PASS ADDED TO THAT LIST DELIBERATELY. Items 11-16 remove
-- columns the application still uses, which is Decision 10 working as intended -
-- the schema wins and the code is scheduled - but scheduled work that is not
-- written down is work that does not happen. The whole of it:
--
--   expense receipts   ShopExpense.files / .s3_key / .item_code, ~40 read and
--                      write sites. report/routes/api.py, expense.py,
--                      download.py, report_detail.py, services/ending.py:1462-1488,
--                      xero/services/publish.py:1061-1065, and four templates -
--                      report/expense.html, edit_report.html:470-477,
--                      report_detail.html:220-225. Reads become a join through
--                      report_expense_attachment; the three `files` formats
--                      normalize_expense_files handles become one shape.
--
--   cash total         Report.actual_cash_total readers join report_cash_summary
--                      instead. ending.py:455,651,1151,1290,1550,
--                      cash_denominations.py:280, report/routes/create.py:310,
--                      opening.py:1114,1149. The NULL test must survive the move.
--
--   cash addition      withdrawal_type -> cash_addition_type and
--                      withdrawal_bank_account removed. api.py:1200-1232,
--                      opening.py (11 sites), download.py:355,591,
--                      services/report_detail.py:350,619, ending.py:1327,1331,
--                      services/shared.py:43-44, xero/services/publish.py:1166-1266.
--
--   receipt_files      Report.receipt_files has no writer; delete the reader and
--                      the S3 delete loop at report/routes/report_detail.py:102,
--                      :127, :448-449, plus four query column lists.
--
--   presence           services/user_presence.py rewritten without
--                      current_entity_id - :100, :115, :164, :176, :195, :204,
--                      :253. Per-company presence is lost until it is. ITEM 14.
--
--   lock dates         Delete backfill_lock_dates_if_needed and both call sites
--                      (entity/services/settings.py:968-1003,1446-1455,
--                      entity/routes/settings.py:1099-1100). Add the "this period
--                      is locked in Xero" error on the report edit / publish
--                      path, checked live through get_organisation_lock_dates
--                      (xero/services/integration.py:142-198). ITEM 15.
--
--   lock dates,        billing-backend: drop the two mirror fields
--   cross-service      (shared_models/models.py:52-53) and move the DRAFT guard
--                      at bills/services/xero_publish_service.py:369-379 - and
--                      bills/api.py:92-145,290 - onto the same live fetch. This
--                      one is not optional: the mirror is `managed = False` and
--                      selects every declared field. ITEM 15.
--
--   financial year     Collect financial_year_end_day / _month during onboarding
--   end                and refresh them on Xero connect. STEP_BASIC (1) is where
--                      the comparable entity scalars already live
--                      (entity/services/onboarding_state.py:272-285; its PUT is
--                      entity/routes/create.py:525); the Xero half is two more
--                      keys read from the org object already in hand at
--                      integration.py:170-190. ITEM 16.
--
-- AND THE ENUM VOCABULARY, item 18: every value the application writes that
-- this file spells differently is listed there, per repo, with line numbers.
-- ===========================================================================

-- ==================================================================
--  ★ 이 스크립트가 생성하는 스키마 이름:  pettycash_test
--
--  ▸ 다른 이름으로 만들고 싶다면 아래 둘 중 하나:
--
--    (A) 에디터에서 "전체 바꾸기" (Ctrl+H)
--          pettycash_test  →  원하는_이름
--        · 이 파일의 pettycash_test 는 100% 대상 스키마만 가리키므로
--          단순 문자열 치환이 안전합니다(다른 식별자에 섞여 있지 않음).
--        · pettycashv2 는 "원본" 스키마입니다. 절대 바꾸지 마세요.
--        · 02_data_foundation.sql / 03_data_reports.sql 도 같은 이름을
--          참조하므로 반드시 같이 바꿔야 합니다(각 24곳 / 64곳).
--
--    (B) 헬퍼 스크립트로 이름만 바꾼 사본 생성 (권장, 원본 보존)
--          powershell -File .\rename_schema.ps1 -To pettycash_dev
--        → .\out\pettycash_dev\ 아래에 01/02/03 이 새 이름으로 생성됨
--
--  ▸ 스키마 이름 규칙: 소문자/숫자/밑줄, 첫 글자는 문자 또는 밑줄
--    (따옴표 없이 쓸 수 있어야 하므로 하이픈·공백·대문자 금지)
-- ==================================================================

-- Auto-generated from Downloads/pettycashv2_full_schema.sql
-- Target schema: pettycash_test (underscore => valid unquoted identifier)
-- Transforms applied vs the source file:
--   * schema pettycashv2 -> pettycash_test
--   * ENUM block uncommented (source had it inside /* ... */)
--   * app_user -> user (source left app_user commented but FKs referenced it)
--   * removed destructive "DROP SCHEMA pettycashv2 CASCADE"
-- Safe to run against a database that still holds the live pettycashv2 schema:
-- it only creates the new pettycash_test schema and never touches pettycashv2.

DROP SCHEMA IF EXISTS pettycash_test CASCADE;
CREATE SCHEMA pettycash_test;

-- ==================================================================
--  pettycashv2  전체 재설계 DDL  (Consolidated Redesign)
--  기준 파일: prestaging_table_08_jul_2026.sql (50+ 테이블 분석)
--
--  주요 재설계 원칙 (DBA)
--   1) draft/v2 제거: report/report_draft/report_v2 → report(status 상태머신)
--                     report_cashcount_draft → report_cash_count(권종 정규화)
--                     shop_expense_draft     → report_expense
--                     report_history_*        → report_history
--   2) 판매채널 정규화: report의 *_sales 컬럼(~18개) → sale_info + report_sale
--                     sale_info.type = electric / delivery / cash / other
--   3) 타입 표준화: varchar(36) → uuid,  double precision(금액) → numeric,
--                  timestamp → timestamptz,  상태값 → enum
--   4) 토큰 분리: user(신원) → app_user + user_token(OAuth 1:1)
--   5) 오타 교정: "desc", sync_statuc, xero_reponse_text, xero_organiztion_id ...
--   6) Django 프레임워크 테이블(auth_*, django_*, sessions)은 재설계 대상에서
--      제외(프레임워크 마이그레이션 관리) → 커스텀 role/permission/app_user 로 일원화
--  Target: PostgreSQL 14+
-- ==================================================================

-- gen_random_uuid(): PG13+ 내장. 구버전이면 아래 주석 해제
-- CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ==========================================
-- 0. Clean up
-- ==========================================

-- ==========================================
-- 1. 공통 트리거 함수 (updated_at 자동 갱신)
-- ==========================================
CREATE OR REPLACE FUNCTION pettycash_test.set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ==========================================
-- 2. ENUM 타입
-- ==========================================
-- ---------------------------------------------------------------------------
-- THE VOCABULARY IS THE REDESIGN'S. THE DATA IS MAPPED. THE CODE FOLLOWS.
--
-- ERA 3 item 5 widened every enum below to whatever the application happened
-- to write, so the load would be lossless. That was REVERSED on 2026-09-15
-- (item 18): the members are the ones `01_schema 2.sql` designed, production
-- values are mapped onto them by the loaders (the CASE expressions live in
-- generators/gen.py ENUM_MAP and nowhere else), and the application changes
-- to write these values in a later pass. Decision 10 applied without exception.
--
-- Every mapping was measured on the production dataset before being decided;
-- the counts are recorded beside each declaration. Where a member the redesign
-- did not have turned out to be a LIVE workflow state (bill_status.returned,
-- publish_state.failed) it was kept, because dropping it would take rows out of
-- a state the user can still act on. Where a member had no writer anywhere it
-- was dropped, whatever the class in bills/models.py declares.
--
-- Four enums are not the redesign's: the two attachment-role enums (Decision 2
-- below, the split stands), expense_attachment_role (new with item 11), the
-- four subscription enums (item 1), and module_code (item 20). Those are unchanged.
-- ---------------------------------------------------------------------------

-- entity_status. Production: connected 49, disconnected 17, onboarding 7,
-- active 7, cancelled 2. The nine active/cancelled entities have never
-- submitted a report or a bill (measured 2026-09-15) and load as
-- 'disconnected'. 'deleted' (list.py:486) is a later code change.
CREATE TYPE pettycash_test.entity_status     AS ENUM
  ('onboarding','connected','disconnected');

-- system_role. Used by user.system_role (item 18 closed D6). Production:
-- normal 117, 'superuser' 1 -> superadmin (mintyliveadmin@dailyminty.com, the
-- global super admin), 'user' 1 -> normal (a stale pre-split value).
CREATE TYPE pettycash_test.system_role       AS ENUM ('normal','admin','superadmin');

-- entity_role: kept as the app's existing 6-level hierarchy (matches ROLE_RANK
-- in services/permission_policy.py) rather than the redesign's owner/admin/
-- member/viewer, so existing user_entity.role / invitation.role values migrate
-- without a lossy remap. Values are ordered low->high privilege.
-- One invitation holds 'shop manager' with a space; the loader maps it.
CREATE TYPE pettycash_test.entity_role       AS ENUM ('entity_base','cashier','shop_manager','accountant','admin','super_admin');

-- invitation_status. Production: accepted 264, pending 49, cancelled 40 ->
-- revoked. invite.py:421 writes 'cancelled' today and changes later.
CREATE TYPE pettycash_test.invitation_status AS ENUM
  ('pending','accepted','expired','revoked');

-- report_status. The app writes only 'draft' and 'posted': 'posted' is set once
-- at ending.py:1568 when the end-of-day wizard finishes, and
-- report_history.html:513 renders it as "Submitted". Whether the report then
-- reached Xero is a different fact, kept in xero_integrated (publish.py:2495),
-- publishing_status and report_history. So 'published' is DERIVED on load
-- (gen.py report_published(), used by BOTH this column and publish_status so
-- they cannot disagree): posted AND xero_integrated_yes AND a report_history
-- row with action = 'published' -> published; any other posted -> submitted.
-- The history row is required by decision: 3 rows carry the flag with no trail
-- (2 say 'completed', 1 says '') and load as submitted / unpublished.
-- Production (2026-09-16 dump): posted 4886, draft 73 -> loaded published 4046,
-- submitted 790, draft 25 (after the 98 reports item 19 drops). Corrected
-- 2026-09-16 twice: from posted -> published (would have marked ~840
-- never-published reports published), then from posted -> submitted (left
-- 'published' unused). ending.py:483 and history_query.py:90 say 'posted' today;
-- publish.py:2495 must write 'published' in the code pass.
CREATE TYPE pettycash_test.report_status     AS ENUM
  ('draft','submitted','published','void');

-- publish_status. The column only exists since ~2026-03-18, so 202 reports
-- published before then hold NULL beside the flag and a 'published' history
-- row; a NULL -> unpublished rule mislabelled them. Derived from the same fact
-- as report_status (gen.py report_published()): published -> completed;
-- source 'failed' and 'partially_published' -> failed; everything else (NULL,
-- '', and the 2 'completed' rows with no history row) -> unpublished. The
-- column is NOT NULL here; NULL was the resting state. Production (2026-09-16
-- dump): completed 3851, failed 11, partially_published 3, NULL/'' 1051 ->
-- loaded completed 4046, failed 14, unpublished 801. 'partially_published'
-- (publish.py:2514, 3 Test_1 reports, no bank transactions) has no member -
-- the app reads it together with 'failed' (history_query.py:102, api.py:1525);
-- whether the UI keeps the "Partially Published" distinction is a code-pass
-- question. 'processing' (submitted.py:301) holds no rows and becomes
-- 'publishing' in the code pass.
CREATE TYPE pettycash_test.publish_status    AS ENUM
  ('unpublished','publishing','completed','failed');

-- discrepancy_type. Production: none 3302, shortage 272 -> short, surplus 188
-- -> over, NULL 2 -> none. cash_count.py:322 writes the long spellings today.
CREATE TYPE pettycash_test.discrepancy_type  AS ENUM
  ('none','over','short');

-- sale_type. Spelled 'electronic', not schema 2's 'electric' (a misspelling).
-- Production: Electronic 617 -> electronic, Delivery 248 -> delivery; the
-- head-only 'Cash' seed (s7a07) -> other. onboarding_state.py:166 and 45 other
-- sites filter on the Capitalised literals today and change later.
CREATE TYPE pettycash_test.sale_type         AS ENUM
  ('electronic','delivery','other');

CREATE TYPE pettycash_test.cash_type         AS ENUM ('coin','note');

-- bill_status. Production: paid 292, submitted 157, voided 26 -> void,
-- partially_paid 4, returned 2, draft 1. 'returned' is NOT in schema 2 but is
-- a live workflow state (return_bill, bills/api.py:431-485: submitted ->
-- returned -> submitted | void), so it stays. authorised / cancelled /
-- sync_failed are declared by class Status and written by nothing.
CREATE TYPE pettycash_test.bill_status       AS ENUM
  ('draft','submitted','returned','partially_paid','paid','void');

-- publish_state: bill.published. Production: published 384, not_published 96
-- -> draft, failed 2. 'failed' is NOT in schema 2 but is written on every Xero
-- push error (xero_publish_service.py:185,292,333,477) and drives the retry
-- action in the frontend, so it stays. The model default ('not_published',
-- models.py:45) changes in the code pass.
CREATE TYPE pettycash_test.publish_state     AS ENUM
  ('draft','published','failed');

-- payment_status. Production: completed 391. 'pending' is the model default
-- and counts toward the bill cap (payment_service.py:26-40); 'partial' has no
-- writer but is schema 2's. cancelled / refunded were declared and never
-- written.
CREATE TYPE pettycash_test.payment_status    AS ENUM
  ('pending','partial','completed','failed');

-- sync_status. Production: success 446, failed 24. 'processing' has no writer
-- but is schema 2's; 'partial' was declared and never written.
CREATE TYPE pettycash_test.sync_status       AS ENUM
  ('pending','processing','success','failed');

-- sync_direction. Production: outbound 470 -> push. 'inbound' is declared and
-- never written.
CREATE TYPE pettycash_test.sync_direction    AS ENUM
  ('push','pull');

-- ---------------------------------------------------------------------------
-- DECISION 2: attachment_role was ONE enum over TWO vocabularies.
--
-- billing-backend declares two separate classes both named AttachmentRole -
-- bills/models.py:214 for bill_attachment, bills/models.py:268 for
-- payment_attachment. They share only 'other'. The single enum the redesign
-- wrote held values from neither, which is why all 89 payment_attachment rows
-- (every one of them 'bank_slip') were rejected.
--
-- Splitting rather than taking the union of seven: a union would let a payment
-- carry 'approval_document', which no code path produces and no reader handles.
-- The union cannot be validated by either service; two enums can.
-- ---------------------------------------------------------------------------
CREATE TYPE pettycash_test.bill_attachment_role AS ENUM
  ('invoice','supporting_document','receipt','approval_document','other','proof');

CREATE TYPE pettycash_test.payment_attachment_role AS ENUM
  ('bank_slip','remittance_proof','payment_receipt','other');

-- expense_attachment_role: a THIRD attachment vocabulary, and ours rather than
-- billing-backend's - report_expense_attachment is a Minty table. Decision 1
-- makes it an enum for exactly that reason.
--
-- 'receipt' is the only value the migration writes;
-- every path that produces one of these rows today is a receipt upload. The
-- other two are declared because an expense can legitimately carry a supplier
-- invoice or a stray document, and adding a value to a live enum is the one
-- change this schema wants to make least.
--
-- Deliberately NOT bill_attachment_role, which also contains 'receipt': that
-- vocabulary belongs to billing-backend (bills/models.py:214) and would couple
-- an expense attachment to a value set the other service is free to change.
CREATE TYPE pettycash_test.expense_attachment_role AS ENUM
  ('receipt','invoice','other');

-- --- subscription / billing -------------------------------------------------
-- Values taken verbatim from blueprints/subscription/constants.py, which is the
-- app's single source for this vocabulary. Not invented here.
--
-- Only the vocabularies WE define become enums. subscription_invoice.status and
-- subscription_email_log.status stay VARCHAR because they mirror Stripe's
-- vocabulary, which we do not control - the same reasoning that keeps the Xero
-- identifiers as VARCHAR rather than uuid. An enum over someone else's value set
-- fails closed the day they add a value.
CREATE TYPE pettycash_test.subscription_phase AS ENUM
  ('trial','active','past_due','scheduled_cancel','cancelled','expired');
CREATE TYPE pettycash_test.extension_state    AS ENUM
  ('pending','invoiced','deleted','credited','refunded');
CREATE TYPE pettycash_test.transfer_status    AS ENUM
  ('pending','charging','charged','accepted','declined','cancelled','expired');
CREATE TYPE pettycash_test.audit_outcome      AS ENUM ('succeeded','aborted');

-- module_code. The module catalogue's vocabulary is closed (two modules,
-- modules.py:32 MODULE_CODES) and item 20 already renames one of them on load;
-- an enum makes the database reject a stray code the way it rejects a stray
-- status. Production: entity_function PETTY_CASH 1, BILL 1 -> PAYMENT_REQUEST;
-- entity_module_subscription and subscription_audit_log hold no rows. Typed on
-- all three function_code columns. billing_plan.code stays VARCHAR - it holds
-- composite keys (BILL+PETTY_CASH) by the item 20 decision. "Super Minty" is
-- that bundle PLAN, not a module, and needs no entity_function row.
CREATE TYPE pettycash_test.module_code        AS ENUM ('PETTY_CASH','PAYMENT_REQUEST');


-- ==================================================================
--  A. 마스터 / 레퍼런스
-- ==================================================================

-- 2.1 currency_info
CREATE TABLE pettycash_test.currency_info (
  id             UUID          NOT NULL DEFAULT gen_random_uuid(),
  currency_code  CHAR(3)       NOT NULL,           -- ISO 4217 (구 iso_code)
  currency_name  VARCHAR(100)  NOT NULL,
  symbol         VARCHAR(10)   NOT NULL DEFAULT '',
  decimal_places SMALLINT      NOT NULL DEFAULT 2,
  is_active      BOOLEAN       NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT currency_info_pkey PRIMARY KEY (id),
  CONSTRAINT currency_info_code_key UNIQUE (currency_code),
  CONSTRAINT chk_currency_code_len CHECK (length(currency_code) = 3)
);

-- 2.2 country_info
CREATE TABLE pettycash_test.country_info (
  country_code    CHAR(2)       NOT NULL,
  alpha3_code     CHAR(3)       NULL,     -- relaxed: source country_info has no alpha3 column
  country_name_en VARCHAR(100)  NOT NULL,
  currency_id     UUID          NULL,
  phone_code      VARCHAR(10)   NULL,
  is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
  display_order   INTEGER       NOT NULL DEFAULT 999,
  CONSTRAINT country_info_pkey PRIMARY KEY (country_code),
  CONSTRAINT fk_country_currency FOREIGN KEY (currency_id)
      REFERENCES pettycash_test.currency_info (id) ON DELETE SET NULL,
  CONSTRAINT chk_country_code_len CHECK (length(country_code) = 2),
  CONSTRAINT chk_alpha3_code_len  CHECK (alpha3_code IS NULL OR length(alpha3_code) = 3)
);


-- ==================================================================
--  B. 사용자 / 권한  (Django auth_* 대체 → app_user/role/permission 일원화)
-- ==================================================================

-- 2.3 app_user  (구 user + auth_user 통합, 토큰은 user_token 으로 분리)
/*
CREATE TABLE pettycash_test.user (
  id                 UUID                     NOT NULL DEFAULT gen_random_uuid(),
  username           VARCHAR(150)             NOT NULL,
  email              VARCHAR(254)             NULL,
  password_hash      VARCHAR(255)             NOT NULL,
  first_name         VARCHAR(150)             NOT NULL DEFAULT '',
  last_name          VARCHAR(150)             NOT NULL DEFAULT '',
  user_phone         VARCHAR(20)              NULL,
  --system_role        pettycash_test.system_role  NOT NULL DEFAULT 'normal',
  is_active          BOOLEAN                  NOT NULL DEFAULT TRUE,
  approved           BOOLEAN                  NOT NULL DEFAULT FALSE,
  xero_user_id       UUID                     NULL,
  xero_email         VARCHAR(100)             NULL,
  reset_token        VARCHAR(100)             NULL,
  reset_token_expiry TIMESTAMPTZ              NULL,
  last_login         TIMESTAMPTZ              NULL,
  created_at         TIMESTAMPTZ              NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ              NOT NULL DEFAULT now(),
  CONSTRAINT app_user_pkey PRIMARY KEY (id),
  CONSTRAINT app_user_username_key UNIQUE (username),
  CONSTRAINT app_user_email_key    UNIQUE (email),
  CONSTRAINT app_user_xero_email_key UNIQUE (xero_email)
);
*/
CREATE TABLE pettycash_test.user (
  id                 UUID                     NOT NULL DEFAULT gen_random_uuid(),
  username           VARCHAR(150)             NOT NULL,
  email              VARCHAR(254)             NULL,   -- migrated = username value (per decision)
  password      VARCHAR(255)             NOT NULL,
  first_name         VARCHAR(150)             NOT NULL DEFAULT '',
  last_name          VARCHAR(150)             NOT NULL DEFAULT '',
  user_phone         VARCHAR(20)              NULL,
  -- The global role. D6 closed 2026-09-15 (item 18): it had arrived commented
  -- out from `01_schema 2.sql` while the app gates superuser on it
  -- (auth/routes/login.py:31, email_auth.py:48, written at invite.py:82).
  -- user_entity.role is per-entity, so there is nowhere else for it to live.
  system_role        pettycash_test.system_role  NOT NULL DEFAULT 'normal',
  is_active          BOOLEAN                  NOT NULL DEFAULT TRUE,
  approved           BOOLEAN                  NOT NULL DEFAULT FALSE,
  xero_user_id       UUID                     NULL,
  xero_email         VARCHAR(100)             NULL,
  -- Password reset. The pair is NULL in every database, but that is the RESTING
  -- state of a working flow, not death: password_reset.py:22-24 writes both and
  -- line 89 clears them, so a value exists only inside a one-hour window.
  reset_token        VARCHAR(100)             NULL,
  reset_token_expiry TIMESTAMPTZ              NULL,
  -- Presence, read by Settings > Users (services/user_presence.py).
  --
  -- The two are not redundant. signed_in_at is the INTENT: stamped at login and
  -- cleared at logout, from either Minty or billing-backend. last_seen_at is the
  -- BACKSTOP for the browser that is simply closed, which sends no logout at all
  -- and would otherwise leave that person listed as signed in forever.
  --
  -- Present therefore means BOTH non-NULL and last_seen_at inside the staleness
  -- window (user_presence.py:110-112): signed_in_at alone answers "did they say
  -- they were here", last_seen_at alone answers "were they here recently", and
  -- only together do they answer "are they here now".
  --
  -- Both are stamped naive HK-local, matching every other timestamp the app
  -- writes on this table.
  signed_in_at       TIMESTAMPTZ              NULL,
  last_seen_at       TIMESTAMPTZ              NULL,
  -- current_entity_id is DROPPED - see ERA 3 item 14. It scoped presence to one
  -- company; nothing here replaces it, and user_presence.py has to change.
  last_login         TIMESTAMPTZ              NULL,
  created_at         TIMESTAMPTZ              NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ              NOT NULL DEFAULT now(),
  -- xero_token stays dropped: referenced only by comments saying it is
  -- deliberately left NULL for passwordless accounts.
  CONSTRAINT user_pkey PRIMARY KEY (id),
  CONSTRAINT user_username_key UNIQUE (username)
  -- No deferred foreign key here any more. current_entity_id was the only column
  -- pointing back at `entities`, so dropping it also dissolved the user <->
  -- entities cycle this file used to work around - see ERA 3 items 4 and 14.
 );
-- 2.4 user_token  (OAuth 토큰 1:1 분리 — 구 user 내장 토큰 + user_token 통합)
CREATE TABLE pettycash_test.user_token (
  id                         UUID        NOT NULL DEFAULT gen_random_uuid(),
  user_id                    UUID        NOT NULL,
  access_token               TEXT        NULL,
  access_token_obtained_at   TIMESTAMPTZ NULL,
  access_token_expires_in    INTEGER     NULL,
  refresh_token              TEXT        NULL,
  refresh_token_last_used_at TIMESTAMPTZ NULL,
  id_token                   TEXT        NULL,
  created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT user_token_pkey PRIMARY KEY (id),
  CONSTRAINT user_token_user_key UNIQUE (user_id),
  CONSTRAINT fk_user_token_user FOREIGN KEY (user_id)
      REFERENCES pettycash_test.user (id) ON DELETE CASCADE
);

-- 2.5 role
CREATE TABLE pettycash_test.role (
  id          UUID         NOT NULL DEFAULT gen_random_uuid(),
  name        VARCHAR(100) NOT NULL,
  description VARCHAR(255) NULL,
  created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT role_pkey PRIMARY KEY (id),
  CONSTRAINT role_name_key UNIQUE (name)
);

-- 2.6 permission
CREATE TABLE pettycash_test.permission (
  id          UUID         NOT NULL DEFAULT gen_random_uuid(),
  code        VARCHAR(100) NOT NULL,
  name        VARCHAR(100) NOT NULL,
  description VARCHAR(255) NULL,
  created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT permission_pkey PRIMARY KEY (id),
  CONSTRAINT permission_code_key UNIQUE (code)
);

-- 2.7 role_permission (M:N)
CREATE TABLE pettycash_test.role_permission (
  role_id       UUID NOT NULL,
  permission_id UUID NOT NULL,
  CONSTRAINT role_permission_pkey PRIMARY KEY (role_id, permission_id),
  CONSTRAINT fk_rp_role       FOREIGN KEY (role_id)       REFERENCES pettycash_test.role (id)       ON DELETE CASCADE,
  CONSTRAINT fk_rp_permission FOREIGN KEY (permission_id) REFERENCES pettycash_test.permission (id) ON DELETE CASCADE
);


-- ==================================================================
--  C. 엔티티 / 회원 / 초대
-- ==================================================================

-- 2.8 entities  (구 entities 컬럼 보강 + 타입 정비)
CREATE TABLE pettycash_test.entities (
  id                    UUID                      NOT NULL DEFAULT gen_random_uuid(),
  country_code          CHAR(2)                   NULL,   -- relaxed: onboarding entities may have no country yet
  currency_id           UUID                      NULL,   -- relaxed: onboarding entities may have no currency yet
  name                  VARCHAR(100)              NOT NULL,
  status                pettycash_test.entity_status NOT NULL DEFAULT 'onboarding',
  -- minimum_qty / deposit_frequency / deposit_day / xero_short_code stay dropped:
  -- model declaration only, no reader, no writer, NULL in all three databases.
  contact_phone         VARCHAR(36)               NULL,   -- was contact_option before c1a01_entity_contact_fields
  business_email        VARCHAR(100)              NULL,
  currency_format       VARCHAR(30)               NULL,
  timezone              VARCHAR(30)               NULL,
  note                  TEXT                      NULL,
  xero_org_id           VARCHAR(36)               NULL,
  xero_tenant_name      VARCHAR(255)              NULL,
  -- Xero's financial year end, as day-of-month and month. Collected during
  -- onboarding and refreshed whenever a Xero connection is (re)established.
  --
  -- The refresh needs no new API call and no new scope: the Organisation response
  -- already fetched at xero/services/integration.py:170 carries
  -- FinancialYearEndDay and FinancialYearEndMonth, and lines 189-190 today read
  -- only the two lock dates out of that same object and discard the rest.
  --
  -- Nullable for the same reason country_code and currency_id are: an entity in
  -- onboarding may not have reached the step that sets them.
  financial_year_end_day   SMALLINT               NULL,
  financial_year_end_month SMALLINT               NULL,
  -- period_lock_date / end_of_year_lock_date are DROPPED - see ERA 3 item 15.
  -- They were write-only: backfilled from Xero, then read by nothing in Minty.
  connected_by_user_id  UUID                      NULL,
  onboarding_saved_step INTEGER                   NULL DEFAULT 9,
  last_connected_at     TIMESTAMPTZ               NULL,
  -- Team-wide "last opened", shown on the Select Company card: WHEN this entity
  -- was last opened and BY WHOM. Entity-level, not per-user - the card answers
  -- "who last touched this company", not "when did I last look at it", which is
  -- why the pair lives here rather than on user_entity.
  --
  -- Written on entity open (entity/routes/modules.py:67-68) and read only to
  -- render that card (entity/routes/list.py:81-92,146-147). The join to `user`
  -- there is an OUTER one, so a never-opened entity still appears in the list.
  --
  -- It deliberately includes superuser visits, which have no user_entity row at
  -- all - a per-membership column could not record them.
  last_accessed_at      TIMESTAMPTZ               NULL,
  last_accessed_by_user_id UUID                   NULL,
  created_at            TIMESTAMPTZ               NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ               NOT NULL DEFAULT now(),
  CONSTRAINT entities_pkey PRIMARY KEY (id),
  CONSTRAINT fk_entities_country  FOREIGN KEY (country_code)         REFERENCES pettycash_test.country_info (country_code) ON DELETE RESTRICT,
  CONSTRAINT fk_entities_currency FOREIGN KEY (currency_id)          REFERENCES pettycash_test.currency_info (id)          ON DELETE RESTRICT,
  CONSTRAINT fk_entities_conn_user FOREIGN KEY (connected_by_user_id) REFERENCES pettycash_test.user (id)              ON DELETE RESTRICT,
  CONSTRAINT fk_entities_last_user FOREIGN KEY (last_accessed_by_user_id) REFERENCES pettycash_test.user (id)          ON DELETE SET NULL,
  CONSTRAINT chk_entities_fy_end_day   CHECK (financial_year_end_day   IS NULL
                                          OR financial_year_end_day   BETWEEN 1 AND 31),
  CONSTRAINT chk_entities_fy_end_month CHECK (financial_year_end_month IS NULL
                                          OR financial_year_end_month BETWEEN 1 AND 12)
);

-- There is no deferred ALTER here any more. It carried fk_user_current_entity,
-- the other half of a user <-> entities cycle that no longer exists now that
-- user.current_entity_id is gone. `entities` still references `user` three
-- times; nothing references back.

-- 2.9 user_entity  (회원 ↔ 엔티티 멤버십 + 역할)
CREATE TABLE pettycash_test.user_entity (
  user_id   UUID                    NOT NULL,
  entity_id UUID                    NOT NULL,
  role      pettycash_test.entity_role NOT NULL,
  approved  BOOLEAN                 NOT NULL DEFAULT FALSE,
  joined_at TIMESTAMPTZ             NULL,
  created_at TIMESTAMPTZ            NOT NULL DEFAULT now(),
  CONSTRAINT user_entity_pkey PRIMARY KEY (user_id, entity_id),
  CONSTRAINT fk_ue_user   FOREIGN KEY (user_id)   REFERENCES pettycash_test.user (id) ON DELETE CASCADE,
  CONSTRAINT fk_ue_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id) ON DELETE CASCADE
);

-- 2.10 invitation
CREATE TABLE pettycash_test.invitation (
  id         UUID                          NOT NULL DEFAULT gen_random_uuid(),
  entity_id  UUID                          NOT NULL,
  email      VARCHAR(150)                  NOT NULL,
  first_name VARCHAR(100)                  NULL,
  last_name  VARCHAR(100)                  NULL,
  role       pettycash_test.entity_role       NOT NULL,
  token      VARCHAR(64)                   NOT NULL,
  status     pettycash_test.invitation_status NOT NULL DEFAULT 'pending',
  invited_by UUID                          NULL,
  accepted_at TIMESTAMPTZ                  NULL,
  expires_at  TIMESTAMPTZ                  NULL,
  created_at  TIMESTAMPTZ                  NOT NULL DEFAULT now(),
  CONSTRAINT invitation_pkey PRIMARY KEY (id),
  CONSTRAINT invitation_token_key UNIQUE (token),
  CONSTRAINT fk_inv_entity     FOREIGN KEY (entity_id)  REFERENCES pettycash_test.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_inv_invited_by FOREIGN KEY (invited_by) REFERENCES pettycash_test.user (id) ON DELETE SET NULL
);

-- 2.11 email_otp
CREATE TABLE pettycash_test.email_otp (
  id          UUID         NOT NULL DEFAULT gen_random_uuid(),
  email       VARCHAR(100) NOT NULL,
  code_hash   VARCHAR(255) NOT NULL,
  attempts    INTEGER      NOT NULL DEFAULT 0,
  expires_at  TIMESTAMPTZ  NOT NULL,
  verified_at TIMESTAMPTZ  NULL,
  created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT email_otp_pkey PRIMARY KEY (id)
);


-- ==================================================================
--  D. Xero 연동 마스터
-- ==================================================================

-- 2.12 account_info  (Xero 계정과목)
CREATE TABLE pettycash_test.account_info (
  id                  UUID         NOT NULL DEFAULT gen_random_uuid(),
  entity_id           UUID         NOT NULL,
  type                VARCHAR(50)  NOT NULL,
  name                VARCHAR(80)  NOT NULL,
  xero_account_id     VARCHAR(36)  NULL,
  xero_code           VARCHAR(50)  NULL,
  status              VARCHAR(50)  NULL,
  class_type          VARCHAR(50)  NULL,
  bank_account_number VARCHAR(50)  NULL,
  bank_account_type   VARCHAR(50)  NULL,
  description         VARCHAR(255) NULL,
  created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT account_info_pkey PRIMARY KEY (id),
  CONSTRAINT uq_account_entity_xero UNIQUE (entity_id, xero_account_id),
  CONSTRAINT fk_account_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id) ON DELETE CASCADE
);

-- 2.13 entity_account_xero  (account_info ↔ Xero org 매핑)
CREATE TABLE pettycash_test.entity_account_xero (
  id              UUID        NOT NULL DEFAULT gen_random_uuid(),
  account_id      UUID        NOT NULL,
  type            VARCHAR(50) NULL,
  xero_org_id     VARCHAR(36) NULL,
  xero_account_id VARCHAR(36) NULL,
  name            VARCHAR(80) NULL,
  is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
  CONSTRAINT entity_account_xero_pkey PRIMARY KEY (id),
  CONSTRAINT fk_eax_account FOREIGN KEY (account_id) REFERENCES pettycash_test.account_info (id) ON DELETE CASCADE
);

-- 2.14 entity_bill_account_xero  (엔티티별 청구 계정 설정 — entity FK 추가)
CREATE TABLE pettycash_test.entity_bill_account_xero (
  id              UUID         NOT NULL DEFAULT gen_random_uuid(),
  entity_id       UUID         NOT NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  account_code    VARCHAR(150) NOT NULL,
  account_name    VARCHAR(150) NOT NULL DEFAULT '',
  account_type    VARCHAR(50)  NOT NULL DEFAULT '',
  xero_account_id VARCHAR(36)  NULL,
  is_default      BOOLEAN      NOT NULL DEFAULT FALSE,
  is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
  is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE,
  sort_order      INTEGER      NOT NULL DEFAULT 0,
  created_by      UUID         NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT entity_bill_account_xero_pkey PRIMARY KEY (id)
);

-- 2.15 entity_bill_currency  (엔티티별 청구 통화 — currency FK 추가)
CREATE TABLE pettycash_test.entity_bill_currency (
  id          UUID        NOT NULL DEFAULT gen_random_uuid(),
  entity_id   UUID        NOT NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  currency_id UUID        NOT NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  is_default  BOOLEAN     NOT NULL DEFAULT FALSE,
  is_enabled  BOOLEAN     NOT NULL DEFAULT TRUE,
  sort_order  INTEGER     NOT NULL DEFAULT 0,
  created_by  UUID        NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT entity_bill_currency_pkey PRIMARY KEY (id),
  CONSTRAINT uq_ebc_entity_currency UNIQUE (entity_id, currency_id)
);

-- 2.16 xero_contact_sync
CREATE TABLE pettycash_test.xero_contact_sync (
  id              UUID         NOT NULL DEFAULT gen_random_uuid(),
  entity_id       UUID         NULL,
  xero_contact_id VARCHAR(36)  NOT NULL,
  xero_org_id     VARCHAR(36)  NULL,
  name            VARCHAR(150) NOT NULL,
  category        VARCHAR(50)  NULL,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT xero_contact_sync_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xero_contact_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id) ON DELETE CASCADE
);


-- ==================================================================
--  E. 엔티티 기능 / 설정
-- ==================================================================

-- 2.17 entity_function
CREATE TABLE pettycash_test.entity_function (
  id            UUID                     NOT NULL DEFAULT gen_random_uuid(),
  function_code pettycash_test.module_code NOT NULL,
  function_name VARCHAR(150) NOT NULL,
  description   TEXT         NOT NULL DEFAULT '',
  is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
  display_order INTEGER      NOT NULL DEFAULT 999,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT entity_function_pkey PRIMARY KEY (id),
  CONSTRAINT entity_function_code_key UNIQUE (function_code)
);

-- 2.18 entity_function_map  (복합 PK로 중복 매핑 방지 — 구 surrogate id 제거)
CREATE TABLE pettycash_test.entity_function_map (
  entity_id          UUID        NOT NULL,
  entity_function_id UUID        NOT NULL,
  is_enabled         BOOLEAN     NOT NULL DEFAULT TRUE,
  settings_json      JSONB       NULL,
  enabled_at         TIMESTAMPTZ NULL,
  disabled_at        TIMESTAMPTZ NULL,
  -- created_by is WHO created the mapping - a real reference to `user`, which is
  -- what this design named it and what it stays.
  --
  -- The running code disagrees today: entity/services/modules.py:534 writes an
  -- actor LABEL here ('onboarding', 'cli', 'entity_create', 'subscription'), and
  -- the model at entity/models/entity_function.py:34 declares String(36) to suit
  -- that. The database is authoritative, so the code changes rather than the
  -- column - see "Required application changes" in the plan.
  --
  -- Nothing has to convert: the column is NULL in every source row, so the
  -- foreign key holds trivially on load.
  --
  -- KNOWN GAP, deliberately accepted: two of the four writers (cli, subscription)
  -- are jobs with no user behind them, so their rows will hold NULL and the four
  -- paths become indistinguishable. If that provenance is wanted back, add a
  -- nullable `actor VARCHAR(20)` beside this column - one column, one line in
  -- _write_pairs. Not done here.
  created_by         UUID        NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT entity_function_map_pkey PRIMARY KEY (entity_id, entity_function_id),
  CONSTRAINT fk_efm_entity   FOREIGN KEY (entity_id)          REFERENCES pettycash_test.entities (id)        ON DELETE CASCADE,
  CONSTRAINT fk_efm_function FOREIGN KEY (entity_function_id) REFERENCES pettycash_test.entity_function (id) ON DELETE RESTRICT,
  CONSTRAINT fk_efm_creator  FOREIGN KEY (created_by)         REFERENCES pettycash_test.user (id)            ON DELETE SET NULL
);

-- 2.19 entity_pettycash_settings  (FOREIGN 누락 오류 수정 + uuid 정비)
CREATE TABLE pettycash_test.entity_pettycash_settings (
  entity_id                   UUID          NOT NULL,
  opening_balance             NUMERIC(14,2) NULL,
  start_date                  DATE          NULL,
  pettycash_account_id        UUID          NULL,
  bank_account_id             UUID          NULL,
  cash_sale_account_id        UUID          NULL,
  discrepancy_bank_account_id UUID          NULL,
  discrepancy_account_id      UUID          NULL,
  director_account_id         UUID          NULL,
  cash_sale_contact_id        UUID          NULL,
  director_contact_id         UUID          NULL,
  discrepancy_contact_id      UUID          NULL,
  created_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT entity_pettycash_settings_pkey PRIMARY KEY (entity_id),
  CONSTRAINT fk_eps_entity        FOREIGN KEY (entity_id)                   REFERENCES pettycash_test.entities (id)          ON DELETE CASCADE,
  CONSTRAINT fk_eps_pettycash_acct FOREIGN KEY (pettycash_account_id)       REFERENCES pettycash_test.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_bank_acct      FOREIGN KEY (bank_account_id)            REFERENCES pettycash_test.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_cashsale_acct  FOREIGN KEY (cash_sale_account_id)       REFERENCES pettycash_test.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_disc_bank_acct FOREIGN KEY (discrepancy_bank_account_id) REFERENCES pettycash_test.account_info (id)     ON DELETE SET NULL,
  CONSTRAINT fk_eps_disc_acct      FOREIGN KEY (discrepancy_account_id)     REFERENCES pettycash_test.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_director_acct  FOREIGN KEY (director_account_id)        REFERENCES pettycash_test.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_eps_cashsale_ct    FOREIGN KEY (cash_sale_contact_id)       REFERENCES pettycash_test.xero_contact_sync (id) ON DELETE SET NULL,
  CONSTRAINT fk_eps_director_ct    FOREIGN KEY (director_contact_id)        REFERENCES pettycash_test.xero_contact_sync (id) ON DELETE SET NULL,
  CONSTRAINT fk_eps_disc_ct        FOREIGN KEY (discrepancy_contact_id)     REFERENCES pettycash_test.xero_contact_sync (id) ON DELETE SET NULL
);


-- ==================================================================
--  F. 현금 / 판매 카탈로그
-- ==================================================================

-- 2.20 cash_info  (권종 마스터 — "desc"→description, country_code→currency_id, serial→uuid)
CREATE TABLE pettycash_test.cash_info (
  id          UUID                  NOT NULL DEFAULT gen_random_uuid(),
  currency_id UUID                  NOT NULL,
  type        pettycash_test.cash_type NULL,
  cash_value  NUMERIC(12,2)         NOT NULL,
  cash_name   VARCHAR(20)           NULL,
  description TEXT                  NULL,
  is_active     BOOLEAN             NOT NULL DEFAULT TRUE,
  display_order INTEGER             NOT NULL DEFAULT 0,
  CONSTRAINT cash_info_pkey PRIMARY KEY (id),
  CONSTRAINT cash_info_currency_value_key UNIQUE (currency_id, cash_value),
  CONSTRAINT fk_cash_currency FOREIGN KEY (currency_id) REFERENCES pettycash_test.currency_info (id) ON DELETE RESTRICT
);

-- 2.21 entity_cash_detail  (엔티티별 현금 재고 — 구 entity_cash_detail_v2)
CREATE TABLE pettycash_test.entity_cash_detail (
  entity_id    UUID                  NOT NULL,
  cash_id      UUID                  NOT NULL,
  cash_type    pettycash_test.cash_type NULL,
  cash_instock NUMERIC(14,2)         NULL,
  description  TEXT                  NULL,
  CONSTRAINT entity_cash_detail_pkey PRIMARY KEY (entity_id, cash_id),
  CONSTRAINT fk_ecd_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id)  ON DELETE CASCADE,
  CONSTRAINT fk_ecd_cash   FOREIGN KEY (cash_id)   REFERENCES pettycash_test.cash_info (id) ON DELETE RESTRICT
);

-- 2.21b entity_cash_setting  (which denominations an entity actually counts)
--   Separate from entity_cash_detail, which holds the running stock. Added at
--   revision c2a02_cash_count, so absent from the schema this file was based on.
CREATE TABLE pettycash_test.entity_cash_setting (
  entity_id     UUID        NOT NULL,
  cash_id       UUID        NOT NULL,   -- head still keys this on the old integer cash_id
  is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
  display_order INTEGER     NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT entity_cash_setting_pkey PRIMARY KEY (entity_id, cash_id),
  CONSTRAINT fk_ecs_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id)  ON DELETE CASCADE,
  CONSTRAINT fk_ecs_cash   FOREIGN KEY (cash_id)   REFERENCES pettycash_test.cash_info (id) ON DELETE CASCADE
);

-- 2.22 sale_info  (판매채널 카탈로그 — type: electronic/delivery/other)
--   구 report 의 *_sales 하드코딩 컬럼을 이 카탈로그의 행으로 정규화.
CREATE TABLE pettycash_test.sale_info (
  id            UUID              NOT NULL DEFAULT gen_random_uuid(),
  type          pettycash_test.sale_type NOT NULL DEFAULT 'other',
  sale_name     VARCHAR(80)       NOT NULL,   -- 예: 'Visa','Deliveroo','Cash'
  value_name    VARCHAR(80)       NULL,
  display_order INTEGER           NULL,
  enabled       BOOLEAN           NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ       NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ       NOT NULL DEFAULT now(),
  CONSTRAINT sale_info_pkey PRIMARY KEY (id),
  CONSTRAINT sale_info_name_key UNIQUE (sale_name)
);

-- 2.23 entity_sale_setting  (엔티티별 사용 판매채널 매핑)
CREATE TABLE pettycash_test.entity_sale_setting (
  entity_id     UUID    NOT NULL,
  sale_id       UUID    NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  display_order INTEGER NULL,
  -- sale_id is NOT a reference to sale_info. entity_sale_setting.py:10 declares
  -- it `primary_key=True, default=lambda: str(uuid.uuid4())` - it mints its own
  -- id. The inferred FK rejected 947 of the table's rows.
  CONSTRAINT entity_sale_setting_pkey PRIMARY KEY (entity_id, sale_id),
  CONSTRAINT fk_ess_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id)  ON DELETE CASCADE
);


-- ==================================================================
--  G. 첨부 / 공유
-- ==================================================================

-- 2.24 attachment  (범용 파일 저장)
-- The `-- no FK: see 7. THE SERVICE BOUNDARY` markers below and in the other billing-backend
-- tables are NOT omissions. attachment, bill, bill_line, bill_audit, payment,
-- payment_attachment, entity_bill_account_xero, entity_bill_currency and the
-- xero_bill_sync tables belong to billing-backend, a separate Django service.
-- Sixteen foreign keys from those tables into Minty's (user, entities,
-- currency_info, xero_contact_sync) were dropped deliberately: not one of the
-- columns is a Django relation - every one is a CharField or UUIDField - the
-- models that do point at Minty tables are `managed = False` read-only mirrors,
-- and production enforces ZERO foreign keys across that boundary.
--
-- The full list and the cost are in the register, up in ERA 3. Search this file
-- for the heading rather than scrolling:   7. THE SERVICE BOUNDARY
CREATE TABLE pettycash_test.attachment (
  id               UUID         NOT NULL DEFAULT gen_random_uuid(),
  original_name    VARCHAR(255) NOT NULL,
  stored_name      VARCHAR(255) NOT NULL,
  file_path        TEXT         NOT NULL,
  file_extension   VARCHAR(20)  NOT NULL DEFAULT '',
  mime_type        VARCHAR(100) NOT NULL,
  -- Nullable, unlike the rest of this table. A row created by an upload always
  -- knows its size; a row RECOVERED FROM A PATH does not, so NULL means "not
  -- asked yet" - which 0 could not say.
  file_size        BIGINT       NULL,
  storage_provider VARCHAR(50)  NOT NULL DEFAULT 's3',
  -- Stays NOT NULL: the empty string is the honest value for a migrated row.
  -- S3's ETag is an MD5 unless the object was uploaded multipart, and putting a
  -- value from the wrong algorithm into a column named sha256 is worse than
  -- leaving it blank.
  checksum_sha256  VARCHAR(128) NOT NULL DEFAULT '',
  uploaded_by      UUID         NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  is_deleted       BOOLEAN      NOT NULL DEFAULT FALSE,
  deleted_at       TIMESTAMPTZ  NULL,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT attachment_pkey PRIMARY KEY (id)
);

-- 2.25 share_link
CREATE TABLE pettycash_test.share_link (
  id               UUID         NOT NULL DEFAULT gen_random_uuid(),
  entity_id        UUID         NOT NULL,
  path_segment     VARCHAR(255) NOT NULL,
  token            TEXT         NOT NULL,
  transaction_date DATE         NOT NULL,
  expires_at       TIMESTAMPTZ  NOT NULL,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT share_link_pkey PRIMARY KEY (id),
  CONSTRAINT share_link_path_key UNIQUE (path_segment),
  CONSTRAINT fk_share_link_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id) ON DELETE CASCADE
);


-- ==================================================================
--  H. 리포트  (★ report/report_draft/report_v2 → report 단일 + status)
-- ==================================================================

-- 2.26 report  (헤더. *_sales 채널 컬럼 제거 → report_sale 로 정규화)
CREATE TABLE pettycash_test.report (
  id                        UUID                          NOT NULL DEFAULT gen_random_uuid(),
  entity_id                 UUID                          NOT NULL,   -- 구 report.company/report_v2.entity_id
  transaction_date          DATE                          NOT NULL,
  next_transaction_date     DATE                          NULL,
  status                    pettycash_test.report_status     NOT NULL DEFAULT 'draft',
  publishing_status         pettycash_test.publish_status    NOT NULL DEFAULT 'unpublished',
  -- 잔액 요약 (double precision → numeric)
  opening_balance           NUMERIC(14,2)                 NULL,
  cash_addition             NUMERIC(14,2)                 NULL,
  adjusted_opening_balance  NUMERIC(14,2)                 NULL,
  cashsale_total            NUMERIC(14,2)                 NULL,
  nocashsale_total          NUMERIC(14,2)                 NULL,
  total_sales               NUMERIC(14,2)                 NULL,
  expense_total             NUMERIC(14,2)                 NULL,
  bank_deposit              NUMERIC(14,2)                 NULL,
  closing_balance           NUMERIC(14,2)                 NULL,
  safe_box_balance          NUMERIC(14,2)                 NULL,
  -- 불일치(discrepancy)
  discrepancy_amount        NUMERIC(14,2)                 NULL,
  discrepancy_type          pettycash_test.discrepancy_type  NOT NULL DEFAULT 'none',
  discrepancy_reason        VARCHAR(300)                  NULL,
  -- 워크플로 진행 상태(구 draft 의 current_section/completed_sections 흡수)
  current_section           VARCHAR(20)                   NULL,
  completed_sections        JSONB                         NULL,
  xero_integrated           BOOLEAN                       NULL,
  -- Added by the report consolidation (r1a01), so absent from the schema this
  -- redesign was written against.
  --
  -- Renamed from withdrawal_type: it has never described a withdrawal. It says
  -- whether the money ADDED to the float came from the company or from someone
  -- personally - 'personal' / 'company', validated at report/routes/api.py:1200 -
  -- which is why it now sits beside cash_addition. See ERA 3 item 13.
  cash_addition_type        VARCHAR(20)                   NULL,
  -- withdrawal_bank_account is DROPPED: the account actually used is the one
  -- configured on entity_pettycash_settings. ERA 3 item 13.
  --
  -- actual_cash_total is DROPPED and replaced by the report_cash_summary view at
  -- the end of this file. It was a total stored beside the very rows it totals.
  -- ERA 3 item 12.
  --
  -- receipt_files is DROPPED. It held a comma-separated list of S3 keys and had
  -- four readers but NO WRITER anywhere in blueprints/, and is NULL in all three
  -- databases. Report-level attachments, if they are ever wanted, belong in
  -- `attachment` the way expense ones now do. ERA 3 item 11.
  created_by                UUID                          NULL,
  submitted_at              TIMESTAMPTZ                   NULL,
  published_at              TIMESTAMPTZ                   NULL,
  created_at                TIMESTAMPTZ                   NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ                   NOT NULL DEFAULT now(),
  CONSTRAINT report_pkey PRIMARY KEY (id),
  CONSTRAINT fk_report_entity  FOREIGN KEY (entity_id)  REFERENCES pettycash_test.entities (id) ON DELETE RESTRICT,
  CONSTRAINT fk_report_creator FOREIGN KEY (created_by) REFERENCES pettycash_test.user (id) ON DELETE SET NULL,
  CONSTRAINT report_entity_date_key UNIQUE (entity_id, transaction_date)  -- 하루 1 리포트
);
COMMENT ON COLUMN pettycash_test.report.status IS
  'draft→submitted→published→void. report_draft/report_v2 를 이 컬럼으로 통합';

-- 2.27 report_sale  (판매채널별 매출 — 구 *_sales 컬럼 + report_sale_detail 정규화)
CREATE TABLE pettycash_test.report_sale (
  id         UUID          NOT NULL DEFAULT gen_random_uuid(),
  report_id  UUID          NOT NULL,
  sale_id    UUID          NOT NULL,
  amount     NUMERIC(14,2) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT report_sale_pkey PRIMARY KEY (id),
  CONSTRAINT report_sale_uq UNIQUE (report_id, sale_id),
  CONSTRAINT fk_rs_report FOREIGN KEY (report_id) REFERENCES pettycash_test.report (id)    ON DELETE CASCADE,
  CONSTRAINT fk_rs_sale   FOREIGN KEY (sale_id)   REFERENCES pettycash_test.sale_info (id) ON DELETE RESTRICT
);

-- 2.28 report_expense  (지출 상세 — 구 report_expense_detail + shop_expense 통합)
CREATE TABLE pettycash_test.report_expense (
  id           UUID          NOT NULL DEFAULT gen_random_uuid(),
  report_id    UUID          NOT NULL,
  account_id   UUID          NULL,
  contact_id   UUID          NULL,
  item         VARCHAR(150)  NULL,
  amount       NUMERIC(14,2) NOT NULL DEFAULT 0,
  remarks      VARCHAR(300)  NULL,
  description  TEXT          NULL,
  -- item_code, attachment_id, files and s3_key are all DROPPED - see ERA 3
  -- item 11. The receipt paths that lived in files / s3_key become `attachment`
  -- rows joined through report_expense_attachment below, which is what
  -- attachment_id was a placeholder for and could never actually do: 1049 of
  -- those 10235 rows hold a COMMA-SEPARATED list, and one uuid column cannot
  -- point at several files.
  created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT report_expense_pkey PRIMARY KEY (id),
  CONSTRAINT fk_re_report     FOREIGN KEY (report_id)     REFERENCES pettycash_test.report (id)            ON DELETE CASCADE,
  CONSTRAINT fk_re_account    FOREIGN KEY (account_id)    REFERENCES pettycash_test.account_info (id)      ON DELETE SET NULL,
  CONSTRAINT fk_re_contact    FOREIGN KEY (contact_id)    REFERENCES pettycash_test.xero_contact_sync (id) ON DELETE SET NULL
);

-- 2.28b report_expense_attachment  (지출 첨부 M:N)
--   The table report_expense.files / s3_key were standing in for. One expense,
--   many receipts, ordered - which is what the source data actually holds and
--   what a single attachment_id could not express.
CREATE TABLE pettycash_test.report_expense_attachment (
  id                 UUID    NOT NULL DEFAULT gen_random_uuid(),
  report_expense_id  UUID    NOT NULL,
  attachment_id      UUID    NOT NULL,
  attachment_role    pettycash_test.expense_attachment_role NOT NULL DEFAULT 'receipt',
  sort_order         INTEGER NOT NULL DEFAULT 0,
  -- Xero's id for the same file once it has been pushed there; empty until it
  -- has been, matching bill_attachment and payment_attachment.
  xero_attachment_id VARCHAR(36) NOT NULL DEFAULT '',
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT report_expense_attachment_pkey PRIMARY KEY (id),
  CONSTRAINT uq_rea_expense_attachment UNIQUE (report_expense_id, attachment_id),
  CONSTRAINT fk_rea_expense    FOREIGN KEY (report_expense_id)
      REFERENCES pettycash_test.report_expense (id) ON DELETE CASCADE,
  CONSTRAINT fk_rea_attachment FOREIGN KEY (attachment_id)
      REFERENCES pettycash_test.attachment (id)     ON DELETE CASCADE
);

-- 2.29 report_cash_count  (권종별 실사 — 구 report_cashcount_draft/report_cash_detail 정규화)
CREATE TABLE pettycash_test.report_cash_count (
  id        UUID    NOT NULL DEFAULT gen_random_uuid(),
  report_id UUID    NOT NULL,
  cash_id   UUID    NOT NULL,
  quantity  INTEGER NOT NULL DEFAULT 0,
  -- Face value AS AT THE TIME OF COUNTING, snapshotted rather than joined, so a
  -- later revaluation of a denomination cannot retroactively change what a
  -- historical report totalled to. Head's model already works this way
  -- (report/models/report_cash_count.py:36-38) and get_cash_count_total() sums
  -- THIS column rather than cash_info - the rebase simply never carried it.
  -- report_cash_summary depends on it. See ERA 3 item 12.
  cash_value NUMERIC(12,2) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT report_cash_count_pkey PRIMARY KEY (id),
  CONSTRAINT report_cash_count_uq UNIQUE (report_id, cash_id),
  CONSTRAINT fk_rcc_report FOREIGN KEY (report_id) REFERENCES pettycash_test.report (id)    ON DELETE CASCADE,
  CONSTRAINT fk_rcc_cash   FOREIGN KEY (cash_id)   REFERENCES pettycash_test.cash_info (id) ON DELETE RESTRICT,
  CONSTRAINT chk_rcc_qty CHECK (quantity >= 0)
);

-- 2.30 report_history  (감사 로그 — report_history/_draft/_v2 통합)
CREATE TABLE pettycash_test.report_history (
  id            UUID         NOT NULL DEFAULT gen_random_uuid(),
  report_id     UUID         NOT NULL,
  user_id       UUID         NULL,
  action        VARCHAR(50)  NOT NULL,
  field_changed VARCHAR(255) NULL,
  old_value     TEXT         NULL,
  new_value     TEXT         NULL,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT report_history_pkey PRIMARY KEY (id),
  CONSTRAINT fk_rh_report FOREIGN KEY (report_id) REFERENCES pettycash_test.report (id)   ON DELETE CASCADE,
  CONSTRAINT fk_rh_user   FOREIGN KEY (user_id)   REFERENCES pettycash_test.user (id) ON DELETE SET NULL
);


-- ==================================================================
--  I. 청구서 / 결제
-- ==================================================================

-- 2.31 bill
CREATE TABLE pettycash_test.bill (
  id                UUID                       NOT NULL DEFAULT gen_random_uuid(),
  entity_id         UUID                       NOT NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  contact_id        UUID                       NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  currency_id       UUID                       NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  contact_name      VARCHAR(100)               NULL,
  bill_number       VARCHAR(50)                NULL,
  reference         VARCHAR(255)               NOT NULL DEFAULT '',
  status            pettycash_test.bill_status    NOT NULL DEFAULT 'draft',
  published         pettycash_test.publish_state  NOT NULL DEFAULT 'draft',
  amount            NUMERIC(14,2)              NOT NULL DEFAULT 0,
  amount_paid       NUMERIC(14,2)              NOT NULL DEFAULT 0,
  description       TEXT                       NOT NULL DEFAULT '',
  invoice_date      DATE                       NULL,
  due_date          DATE                       NULL,
  xero_account_code VARCHAR(20)                NOT NULL DEFAULT '',
  created_by        UUID                       NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  created_at        TIMESTAMPTZ                NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ                NOT NULL DEFAULT now(),
  CONSTRAINT bill_pkey PRIMARY KEY (id)
);

-- 2.32 bill_line  (구 bill_line_item)
CREATE TABLE pettycash_test.bill_line (
  id           UUID          NOT NULL DEFAULT gen_random_uuid(),
  bill_id      UUID          NOT NULL,
  description  TEXT          NOT NULL,
  quantity     NUMERIC(12,4) NOT NULL DEFAULT 1,
  unit_amount  NUMERIC(14,2) NOT NULL DEFAULT 0,
  line_amount  NUMERIC(14,2) NOT NULL DEFAULT 0,
  account_code VARCHAR(20)   NOT NULL DEFAULT '',
  account_name VARCHAR(150)  NOT NULL DEFAULT '',
  tax_type     VARCHAR(30)   NOT NULL DEFAULT '',
  sort_order   INTEGER       NOT NULL DEFAULT 0,
  note         TEXT          NOT NULL DEFAULT '',
  created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT bill_line_pkey PRIMARY KEY (id),
  CONSTRAINT fk_bl_bill FOREIGN KEY (bill_id) REFERENCES pettycash_test.bill (id) ON DELETE CASCADE
);

-- 2.33 bill_attachment
CREATE TABLE pettycash_test.bill_attachment (
  id                 UUID                          NOT NULL DEFAULT gen_random_uuid(),
  bill_id            UUID                          NOT NULL,
  attachment_id      UUID                          NOT NULL,
  attachment_role    pettycash_test.bill_attachment_role NOT NULL DEFAULT 'other',
  sort_order         INTEGER                       NOT NULL DEFAULT 0,
  note               TEXT                          NOT NULL DEFAULT '',
  xero_attachment_id VARCHAR(36)                   NOT NULL DEFAULT '',
  xero_filename      VARCHAR(255)                  NOT NULL DEFAULT '',
  created_by         UUID                          NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  created_at         TIMESTAMPTZ                   NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ                   NOT NULL DEFAULT now(),
  CONSTRAINT bill_attachment_pkey PRIMARY KEY (id),
  CONSTRAINT fk_ba_bill       FOREIGN KEY (bill_id)       REFERENCES pettycash_test.bill (id)       ON DELETE CASCADE,
  CONSTRAINT fk_ba_attachment FOREIGN KEY (attachment_id) REFERENCES pettycash_test.attachment (id) ON DELETE CASCADE
);

-- 2.34 payment
CREATE TABLE pettycash_test.payment (
  id              UUID                       NOT NULL DEFAULT gen_random_uuid(),
  bill_id         UUID                       NOT NULL,
  payment_date    DATE                       NULL,
  amount          NUMERIC(14,2)              NOT NULL DEFAULT 0,
  currency_id     UUID                       NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  payment_method  VARCHAR(50)                NOT NULL DEFAULT '',
  payment_status  pettycash_test.payment_status NOT NULL DEFAULT 'pending',
  reference_no    VARCHAR(100)               NOT NULL DEFAULT '',
  note            TEXT                       NOT NULL DEFAULT '',
  xero_payment_id VARCHAR(36)                NOT NULL DEFAULT '',
  created_by      UUID                       NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  created_at      TIMESTAMPTZ                NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ                NOT NULL DEFAULT now(),
  CONSTRAINT payment_pkey PRIMARY KEY (id),
  CONSTRAINT fk_payment_bill     FOREIGN KEY (bill_id)     REFERENCES pettycash_test.bill (id)          ON DELETE CASCADE
);

-- 2.35 payment_attachment
CREATE TABLE pettycash_test.payment_attachment (
  id                 UUID                        NOT NULL DEFAULT gen_random_uuid(),
  payment_id         UUID                        NOT NULL,
  attachment_id      UUID                        NOT NULL,
  attachment_role    pettycash_test.payment_attachment_role NOT NULL DEFAULT 'other',
  sort_order         INTEGER                     NOT NULL DEFAULT 0,
  note               TEXT                        NOT NULL DEFAULT '',
  xero_attachment_id VARCHAR(36)                 NOT NULL DEFAULT '',
  xero_filename      VARCHAR(255)                NOT NULL DEFAULT '',
  created_by         UUID                        NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  created_at         TIMESTAMPTZ                 NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ                 NOT NULL DEFAULT now(),
  CONSTRAINT payment_attachment_pkey PRIMARY KEY (id),
  CONSTRAINT fk_pa_payment    FOREIGN KEY (payment_id)    REFERENCES pettycash_test.payment (id)    ON DELETE CASCADE,
  CONSTRAINT fk_pa_attachment FOREIGN KEY (attachment_id) REFERENCES pettycash_test.attachment (id) ON DELETE CASCADE
);

-- 2.36 bill_audit  (구 audit — bill 전용 감사)
CREATE TABLE pettycash_test.bill_audit (
  id      UUID         NOT NULL DEFAULT gen_random_uuid(),
  bill_id UUID         NOT NULL,
  user_id UUID         NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  action  VARCHAR(100) NOT NULL,
  detail  TEXT         NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT bill_audit_pkey PRIMARY KEY (id),
  CONSTRAINT fk_audit_bill FOREIGN KEY (bill_id) REFERENCES pettycash_test.bill (id)     ON DELETE CASCADE
);


-- ==================================================================
--  J. Xero 동기화 (작업/로그)
-- ==================================================================

-- 2.37 xero_bill_sync
CREATE TABLE pettycash_test.xero_bill_sync (
  id                     UUID                        NOT NULL DEFAULT gen_random_uuid(),
  bill_id                UUID                        NOT NULL,
  sync_direction         pettycash_test.sync_direction  NOT NULL,
  sync_type              VARCHAR(30)                 NOT NULL,
  sync_status            pettycash_test.sync_status     NOT NULL DEFAULT 'pending',
  request_type           VARCHAR(20)                 NOT NULL DEFAULT '',
  request_status         VARCHAR(30)                 NOT NULL DEFAULT '',
  request_contact_id     VARCHAR(36)                 NOT NULL DEFAULT '',
  request_invoice_number VARCHAR(100)                NOT NULL DEFAULT '',
  request_reference      VARCHAR(255)                NOT NULL DEFAULT '',
  request_invoice_date   DATE                        NULL,
  request_due_date       DATE                        NULL,
  response_invoice_id    VARCHAR(36)                 NOT NULL DEFAULT '',
  response_status        VARCHAR(30)                 NOT NULL DEFAULT '',
  response_amount_due    NUMERIC(12,2)               NULL,
  response_amount_paid   NUMERIC(12,2)               NULL,
  response_total         NUMERIC(12,2)               NULL,
  response_currency_code VARCHAR(10)                 NOT NULL DEFAULT '',
  http_status_code       INTEGER                     NULL,
  idempotency_key        VARCHAR(100)                NOT NULL DEFAULT '',
  -- Present and NOT NULL at head; absent from the schema this redesign was
  -- written against. response_invoice_number and xero_response_id both carry
  -- real values in production.
  response_invoice_number VARCHAR(100)               NOT NULL DEFAULT '',
  xero_response_id       VARCHAR(36)                 NOT NULL DEFAULT '',
  xero_provider_name     VARCHAR(100)                NOT NULL DEFAULT '',
  xero_datetime_utc      VARCHAR(100)                NOT NULL DEFAULT '',
  retry_count            INTEGER                     NOT NULL DEFAULT 0,
  last_retry_at          TIMESTAMPTZ                 NULL,
  has_errors             BOOLEAN                     NOT NULL DEFAULT FALSE,
  error_message          TEXT                        NOT NULL DEFAULT '',
  requested_by           UUID                        NULL,  -- no FK: see 7. THE SERVICE BOUNDARY
  requested_at           TIMESTAMPTZ                 NULL,
  responded_at           TIMESTAMPTZ                 NULL,
  created_at             TIMESTAMPTZ                 NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ                 NOT NULL DEFAULT now(),
  CONSTRAINT xero_bill_sync_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xbs_bill    FOREIGN KEY (bill_id)      REFERENCES pettycash_test.bill (id)     ON DELETE CASCADE
);

-- 2.38 xero_bill_sync_line
CREATE TABLE pettycash_test.xero_bill_sync_line (
  id                    UUID          NOT NULL DEFAULT gen_random_uuid(),
  xero_bill_sync_id     UUID          NOT NULL,
  bill_line_id          UUID          NULL,
  description           TEXT          NOT NULL DEFAULT '',
  quantity              NUMERIC(12,4) NOT NULL DEFAULT 0,
  unit_amount           NUMERIC(12,2) NOT NULL DEFAULT 0,
  line_amount           NUMERIC(12,2) NOT NULL DEFAULT 0,
  account_code          VARCHAR(20)   NOT NULL DEFAULT '',
  tax_type              VARCHAR(30)   NOT NULL DEFAULT '',
  sort_order            INTEGER       NOT NULL DEFAULT 0,
  response_line_item_id VARCHAR(36)   NOT NULL DEFAULT '',
  response_account_id   VARCHAR(36)   NOT NULL DEFAULT '',
  response_tax_amount   NUMERIC(12,2) NULL,
  created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT xero_bill_sync_line_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xbsl_sync FOREIGN KEY (xero_bill_sync_id) REFERENCES pettycash_test.xero_bill_sync (id) ON DELETE CASCADE,
  CONSTRAINT fk_xbsl_line FOREIGN KEY (bill_line_id)      REFERENCES pettycash_test.bill_line (id)       ON DELETE SET NULL
);

-- 2.39 xero_bill_response_line
CREATE TABLE pettycash_test.xero_bill_response_line (
  id                UUID          NOT NULL DEFAULT gen_random_uuid(),
  xero_bill_sync_id UUID          NOT NULL,
  xero_line_item_id VARCHAR(36)   NOT NULL DEFAULT '',
  description       TEXT          NOT NULL DEFAULT '',
  quantity          NUMERIC(12,4) NOT NULL DEFAULT 0,
  unit_amount       NUMERIC(12,2) NOT NULL DEFAULT 0,
  line_amount       NUMERIC(12,2) NOT NULL DEFAULT 0,
  tax_type          VARCHAR(30)   NOT NULL DEFAULT '',
  tax_amount        NUMERIC(12,2) NOT NULL DEFAULT 0,
  account_code      VARCHAR(20)   NOT NULL DEFAULT '',
  account_id        VARCHAR(36)   NOT NULL DEFAULT '',
  validation_errors JSONB         NULL,
  created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT xero_bill_response_line_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xbrl_sync FOREIGN KEY (xero_bill_sync_id) REFERENCES pettycash_test.xero_bill_sync (id) ON DELETE CASCADE
);

-- 2.40 xero_bill_sync_payload
CREATE TABLE pettycash_test.xero_bill_sync_payload (
  id                UUID        NOT NULL DEFAULT gen_random_uuid(),
  xero_bill_sync_id UUID        NOT NULL,
  request_json      JSONB       NULL,
  response_json     JSONB       NULL,
  request_headers   JSONB       NULL,
  response_headers  JSONB       NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT xero_bill_sync_payload_pkey PRIMARY KEY (id),
  CONSTRAINT xero_bill_sync_payload_key UNIQUE (xero_bill_sync_id),
  CONSTRAINT fk_xbsp_sync FOREIGN KEY (xero_bill_sync_id) REFERENCES pettycash_test.xero_bill_sync (id) ON DELETE CASCADE
);

-- 2.41 xero_bank_transaction  (sync_report_id → report 로 연결)
CREATE TABLE pettycash_test.xero_bank_transaction (
  id                       UUID          NOT NULL DEFAULT gen_random_uuid(),
  sync_report_id           UUID          NULL,
  type                     VARCHAR(10)   NOT NULL,
  xero_contact_id          VARCHAR(36)   NOT NULL,
  xero_contact_name        VARCHAR(100)  NULL,
  unit_amount              NUMERIC(14,2) NOT NULL,
  quantity                 NUMERIC(12,2) NOT NULL,
  xero_account_id          VARCHAR(36)   NOT NULL,
  xero_account_code        VARCHAR(10)   NULL,
  description              TEXT          NULL,
  xero_bank_account_id     VARCHAR(36)   NOT NULL,
  xero_bank_transaction_id VARCHAR(36)   NOT NULL,
  subtotal                 NUMERIC(14,2) NULL,
  total_tax                NUMERIC(14,2) NULL,
  total                    NUMERIC(14,2) NULL,
  status                   VARCHAR(10)   NULL,
  created_at               TIMESTAMPTZ   NULL DEFAULT now(),
  CONSTRAINT xero_bank_transaction_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xbt_report FOREIGN KEY (sync_report_id) REFERENCES pettycash_test.report (id) ON DELETE CASCADE
);

-- 2.42 xero_bank_transfer
CREATE TABLE pettycash_test.xero_bank_transfer (
  id                       UUID          NOT NULL DEFAULT gen_random_uuid(),
  sync_report_id           UUID          NOT NULL,
  from_bank_account_id     VARCHAR(36)   NOT NULL,
  to_bank_account_id       VARCHAR(36)   NOT NULL,
  amount                   NUMERIC(14,2) NOT NULL,
  transfer_date            TIMESTAMPTZ   NOT NULL,
  xero_bank_transfer_id    VARCHAR(36)   NOT NULL,
  from_bank_transaction_id VARCHAR(36)   NOT NULL,
  to_bank_transaction_id   VARCHAR(36)   NOT NULL,
  status                   VARCHAR(10)   NULL,
  error_message            TEXT          NULL,
  created_at               TIMESTAMPTZ   NOT NULL DEFAULT now(),   -- item 22
  updated_at               TIMESTAMPTZ   NOT NULL DEFAULT now(),   -- item 22
  CONSTRAINT xero_bank_transfer_pkey PRIMARY KEY (id),
  CONSTRAINT fk_xbtr_report FOREIGN KEY (sync_report_id) REFERENCES pettycash_test.report (id) ON DELETE CASCADE
);

-- 2.43 xero_report_sync  (오타 교정: sync_statuc→sync_status, xero_reponse_text→xero_response_text)
CREATE TABLE pettycash_test.xero_report_sync (
  id                 UUID        NOT NULL DEFAULT gen_random_uuid(),
  report_id          UUID        NOT NULL,
  sync_status        VARCHAR(20) NULL,
  reported_at        TIMESTAMPTZ NULL,
  completed_at       TIMESTAMPTZ NULL,
  xero_response_text TEXT        NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),   -- item 22
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),   -- item 22
  CONSTRAINT xero_report_sync_pkey PRIMARY KEY (id),
  CONSTRAINT xero_report_sync_report_key UNIQUE (report_id),
  CONSTRAINT fk_xrs_report FOREIGN KEY (report_id) REFERENCES pettycash_test.report (id) ON DELETE CASCADE
);


-- ==================================================================
--  K. 구독 / 청구  (Minty's own billing)
--
--  Thirteen tables that did NOT exist in the schema this redesign was written
--  against - they arrive at revision a1b2c3d4e5f7, well after it. Every one
--  declares a model and is referenced by 3-23 files, so leaving them out would
--  take subscriptions, Stripe billing and terms consent offline.
--
--  Ported into this file's idiom: uuid keys defaulting to gen_random_uuid(),
--  TIMESTAMPTZ throughout, and enums for the status vocabularies THIS APP
--  defines. The ones Stripe defines stay VARCHAR - see the note by the enum
--  declarations.
--
--  MONEY IS INTEGER CENTS here, not NUMERIC, unlike the rest of the schema.
--  That is deliberate: these amounts come from and go to Stripe, whose API is
--  integer minor units. Converting to NUMERIC(14,2) would mean rounding at
--  every boundary for no gain. The petty-cash side stays NUMERIC.
-- ==================================================================

-- 2.44 billing_plan
CREATE TABLE pettycash_test.billing_plan (
  id              UUID         NOT NULL DEFAULT gen_random_uuid(),
  code            VARCHAR(100) NOT NULL,
  display_name    VARCHAR(255) NOT NULL,
  amount          INTEGER      NOT NULL,          -- cents
  currency        CHAR(3)      NOT NULL,
  interval_months INTEGER      NOT NULL DEFAULT 1,
  is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT billing_plan_pkey PRIMARY KEY (id),
  CONSTRAINT billing_plan_code_key UNIQUE (code),
  CONSTRAINT fk_billing_plan_currency FOREIGN KEY (currency)
      REFERENCES pettycash_test.currency_info (currency_code)
);

-- 2.45 billing_policy  (singleton: the tunable trial / grace / retry windows)
CREATE TABLE pettycash_test.billing_policy (
  id                      INTEGER      NOT NULL,
  trial_days              INTEGER      NOT NULL DEFAULT 30,
  paid_cancel_access_days INTEGER      NOT NULL DEFAULT 30,
  past_due_window_days    INTEGER      NOT NULL DEFAULT 15,
  retry_offsets_days      VARCHAR(100) NOT NULL DEFAULT '1,2,3,4,5,6,7,8,9,10,11,12,13',
  updated_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_by              VARCHAR(255) NULL,
  CONSTRAINT billing_policy_pkey PRIMARY KEY (id),
  CONSTRAINT ck_billing_policy_singleton       CHECK (id = 1),
  CONSTRAINT ck_billing_policy_trial_days      CHECK (trial_days >= 0),
  CONSTRAINT ck_billing_policy_cancel_days     CHECK (paid_cancel_access_days >= 0),
  CONSTRAINT ck_billing_policy_past_due_window CHECK (past_due_window_days >= 3),
  CONSTRAINT ck_billing_policy_retry_offsets_format
      CHECK (retry_offsets_days ~ '^[0-9]+(,[0-9]+)*$')
);

-- 2.46 payer_billing_group  (a billing account: its identity, its cards, and
--      everything it pays for)
--
-- The table keeps its old name - renaming it is a cutover-time change, not an
-- additive one - but it is now the BILLING ACCOUNT the payer creates and names,
-- not merely a card with a cycle attached. See ERA 3 item 17.
CREATE TABLE pettycash_test.payer_billing_group (
  id                       UUID         NOT NULL DEFAULT gen_random_uuid(),
  payer_user_id            UUID         NOT NULL,
  -- The card this account CHARGES. The rest of the account's cards live in
  -- billing_account_payment_method (2.47); this column is the default among
  -- them and stays here because renewals and dunning read it directly. Mutable:
  -- replacing an expiring card is an UPDATE of one column, and the cycle below
  -- survives it.
  stripe_payment_method_id VARCHAR(255) NOT NULL,
  -- The account's identity, collected when the payer creates it. NULL on every
  -- row that predates billing accounts, which is why neither is NOT NULL.
  billing_email            VARCHAR(255) NULL,
  billing_company          VARCHAR(255) NULL,
  -- The cycle. NOW PER ACCOUNT, not per card - one invoice is raised per
  -- account, so this is still the grain the money is collected at.
  paid_through             TIMESTAMPTZ  NULL,
  dunning_started_at       TIMESTAMPTZ  NULL,
  dunning_attempts         INTEGER      NOT NULL DEFAULT 0,
  created_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT payer_billing_group_pkey PRIMARY KEY (id),
  -- uq_payer_billing_group_payer_card IS GONE. It read (payer_user_id,
  -- stripe_payment_method_id) and said a payer could not hold two accounts on
  -- one card. An account may now hold SEVERAL cards, so a card no longer
  -- identifies an account and the constraint would forbid the ordinary case of
  -- two accounts sharing one card. What it was protecting - two accounts
  -- claiming one entity's renewal - is held by entity_billing_group's own
  -- UNIQUE (entity_id, payer_user_id) instead.
  CONSTRAINT fk_pbg_user FOREIGN KEY (payer_user_id) REFERENCES pettycash_test.user (id)
);

-- 2.47 billing_account_payment_method  (the cards on one billing account)
--
-- The shelf behind payer_billing_group.stripe_payment_method_id. That column
-- names the ONE card an account charges; this table is every card the payer has
-- put on that account, exactly one of which is the default.
--
-- WHY BOTH. The default is duplicated deliberately - here as is_default, there
-- as the id itself - because renewals and dunning read the account row and must
-- not join to find out which card to charge. set_group_default_card writes both
-- or neither; a divergence between them means the account charges a card the
-- payer is not being shown.
--
-- Only ids are held. The number is typed into Stripe Elements and confirmed
-- against a SetupIntent; no PAN reaches this process, this table or these logs.
CREATE TABLE pettycash_test.billing_account_payment_method (
  id                       UUID         NOT NULL DEFAULT gen_random_uuid(),
  billing_group_id         UUID         NOT NULL,
  stripe_payment_method_id VARCHAR(255) NOT NULL,
  is_default               BOOLEAN      NOT NULL DEFAULT false,
  created_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT billing_account_payment_method_pkey PRIMARY KEY (id),
  CONSTRAINT uq_bapm_group_card UNIQUE (billing_group_id, stripe_payment_method_id),
  -- CASCADE, unlike the other section K foreign keys: a row here is not a fact
  -- about the payment in its own right, it is the account's list. Deleting the
  -- account and leaving the list would strand rows nothing can reach.
  CONSTRAINT fk_bapm_group FOREIGN KEY (billing_group_id)
      REFERENCES pettycash_test.payer_billing_group (id) ON DELETE CASCADE
);

-- 2.48 entity_billing_group  (which group pays for which entity)
CREATE TABLE pettycash_test.entity_billing_group (
  id               UUID        NOT NULL DEFAULT gen_random_uuid(),
  entity_id        UUID        NOT NULL,
  payer_user_id    UUID        NOT NULL,
  billing_group_id UUID        NOT NULL,
  source           VARCHAR(20) NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT entity_billing_group_pkey PRIMARY KEY (id),
  CONSTRAINT uq_entity_billing_group_entity_payer UNIQUE (entity_id, payer_user_id),
  CONSTRAINT fk_ebg_entity FOREIGN KEY (entity_id)        REFERENCES pettycash_test.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_ebg_user   FOREIGN KEY (payer_user_id)    REFERENCES pettycash_test.user (id),
  CONSTRAINT fk_ebg_group  FOREIGN KEY (billing_group_id) REFERENCES pettycash_test.payer_billing_group (id)
);

-- 2.49 entity_billing_consent
CREATE TABLE pettycash_test.entity_billing_consent (
  id         UUID        NOT NULL DEFAULT gen_random_uuid(),
  entity_id  UUID        NOT NULL,
  user_id    UUID        NOT NULL,
  source     VARCHAR(20) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT entity_billing_consent_pkey PRIMARY KEY (id),
  CONSTRAINT uq_entity_billing_consent_entity_user UNIQUE (entity_id, user_id),
  CONSTRAINT fk_ebcon_entity FOREIGN KEY (entity_id) REFERENCES pettycash_test.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_ebcon_user   FOREIGN KEY (user_id)   REFERENCES pettycash_test.user (id)     ON DELETE CASCADE
);

-- 2.50 entity_module_subscription  (the access gate, per entity per module)
CREATE TABLE pettycash_test.entity_module_subscription (
  id               UUID                              NOT NULL DEFAULT gen_random_uuid(),
  entity_id        UUID                              NOT NULL,
  function_code    pettycash_test.module_code        NOT NULL,
  payer_user_id    UUID                              NULL,   -- NULL until billing is confirmed
  phase            pettycash_test.subscription_phase NOT NULL,
  app_access_until TIMESTAMPTZ                       NULL,
  trial_end        TIMESTAMPTZ                       NULL,
  first_billed_at  TIMESTAMPTZ                       NULL,
  billed_through   TIMESTAMPTZ                       NULL,
  extension_amount INTEGER                           NULL,   -- cents
  extension_state  pettycash_test.extension_state    NULL,
  created_at       TIMESTAMPTZ                       NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ                       NOT NULL DEFAULT now(),
  CONSTRAINT entity_module_subscription_pkey PRIMARY KEY (id),
  CONSTRAINT uq_ems_entity_code UNIQUE (entity_id, function_code),
  CONSTRAINT fk_ems_entity FOREIGN KEY (entity_id)     REFERENCES pettycash_test.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_ems_user   FOREIGN KEY (payer_user_id) REFERENCES pettycash_test.user (id)     ON DELETE CASCADE
);

-- 2.51 user_stripe_customer
CREATE TABLE pettycash_test.user_stripe_customer (
  id                 UUID         NOT NULL DEFAULT gen_random_uuid(),
  user_id            UUID         NOT NULL,
  stripe_customer_id VARCHAR(255) NOT NULL,
  anchor_at          TIMESTAMPTZ  NULL,
  currency           CHAR(3)      NULL,
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT user_stripe_customer_pkey PRIMARY KEY (id),
  CONSTRAINT user_stripe_customer_user_key   UNIQUE (user_id),
  CONSTRAINT user_stripe_customer_stripe_key UNIQUE (stripe_customer_id),
  CONSTRAINT fk_usc_user     FOREIGN KEY (user_id)  REFERENCES pettycash_test.user (id) ON DELETE CASCADE,
  CONSTRAINT fk_usc_currency FOREIGN KEY (currency) REFERENCES pettycash_test.currency_info (currency_code)
);

-- 2.52 subscription_invoice
--   status and payment_method mirror Stripe's vocabulary, so they stay VARCHAR.
CREATE TABLE pettycash_test.subscription_invoice (
  id                 UUID         NOT NULL DEFAULT gen_random_uuid(),
  payer_user_id      UUID         NOT NULL,
  billing_group_id   UUID         NULL,
  stripe_customer_id VARCHAR(255) NULL,
  external_id        VARCHAR(255) NULL,
  period_start       TIMESTAMPTZ  NOT NULL,
  period_end         TIMESTAMPTZ  NOT NULL,
  currency           CHAR(3)      NOT NULL,
  total              INTEGER      NOT NULL DEFAULT 0,   -- cents
  status             VARCHAR(20)  NOT NULL,
  memo               VARCHAR(500) NULL,
  payment_method     VARCHAR(100) NULL,
  hosted_invoice_url VARCHAR(500) NULL,
  -- UNIQUE, via idx_si_idempotency_key at the end of this file. That index is not
  -- a lookup aid: it is the DOUBLE-CHARGE GUARD. subscription/services/billing_gateway.py
  -- claims the key BEFORE the charge and relies on the database to refuse a second
  -- claim, and subscription_transfer.py:102 names it as the mechanism. Nullable, so
  -- a mid-period purchase with no natural key is unconstrained - which is what the
  -- live schema does too.
  idempotency_key    VARCHAR(255) NULL,
  issued_at          TIMESTAMPTZ  NULL,
  paid_at            TIMESTAMPTZ  NULL,
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT subscription_invoice_pkey PRIMARY KEY (id),
  CONSTRAINT fk_si_user     FOREIGN KEY (payer_user_id)    REFERENCES pettycash_test.user (id),
  CONSTRAINT fk_si_group    FOREIGN KEY (billing_group_id) REFERENCES pettycash_test.payer_billing_group (id) ON DELETE SET NULL,
  CONSTRAINT fk_si_currency FOREIGN KEY (currency)         REFERENCES pettycash_test.currency_info (currency_code)
);

-- 2.53 subscription_invoice_line
CREATE TABLE pettycash_test.subscription_invoice_line (
  id           UUID         NOT NULL DEFAULT gen_random_uuid(),
  invoice_id   UUID         NOT NULL,
  entity_id    UUID         NOT NULL,
  entity_name  VARCHAR(255) NOT NULL,
  product_name VARCHAR(255) NOT NULL,
  amount       INTEGER      NOT NULL,   -- cents
  kind         VARCHAR(20)  NOT NULL DEFAULT 'full',
  at           TIMESTAMPTZ  NULL,
  -- What the line PAID FOR, written by the biller when the invoice is issued (item 23):
  -- the days, half-open [period_start, period_end) like the invoice's own period, and
  -- the price per billing period they were charged at (cents; positive on a credit
  -- too - amount carries the sign). A renewal is the whole period at its plan's price;
  -- a mid-period start, upgrade or the credit for the plan it replaced runs from the
  -- change to the period's end; an access extension runs from what the company was
  -- paid through to its access end. NULL on every line issued before these existed,
  -- and unit_amount NULL on an extension whose rate stepped part-way (a bundle
  -- winding down, its modules ending on different days) - it had no single rate.
  period_start TIMESTAMPTZ  NULL,
  period_end   TIMESTAMPTZ  NULL,
  unit_amount  INTEGER      NULL,   -- cents
  created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT subscription_invoice_line_pkey PRIMARY KEY (id),
  CONSTRAINT fk_sil_invoice FOREIGN KEY (invoice_id) REFERENCES pettycash_test.subscription_invoice (id) ON DELETE CASCADE,
  CONSTRAINT fk_sil_entity  FOREIGN KEY (entity_id)  REFERENCES pettycash_test.entities (id)
);

-- 2.54 subscription_transfer  (handing an entity's bill to a new payer)
--   charging / charged are the NON-terminal states: an accept that got part-way,
--   because the charge and the payer flip commit separately.
CREATE TABLE pettycash_test.subscription_transfer (
  id                      UUID                            NOT NULL DEFAULT gen_random_uuid(),
  entity_id               UUID                            NOT NULL,
  from_user_id            UUID                            NOT NULL,
  to_user_id              UUID                            NOT NULL,
  status                  pettycash_test.transfer_status  NOT NULL,
  created_at              TIMESTAMPTZ                     NOT NULL DEFAULT now(),
  expires_at              TIMESTAMPTZ                     NOT NULL,
  responded_at            TIMESTAMPTZ                     NULL,
  accepted_billed_through TIMESTAMPTZ                     NULL,
  accepted_anchor_at      TIMESTAMPTZ                     NULL,
  quoted_amount           INTEGER                         NULL,   -- cents
  quoted_currency         CHAR(3)                         NULL,
  charge_attempt          INTEGER                         NOT NULL DEFAULT 0,
  charge_key              VARCHAR(120)                    NULL,
  charge_invoice_id       VARCHAR(64)                     NULL,
  -- NOT NULL = this handover's first charge has not been collected, and becomes
  -- collectable at this instant (the day the outgoing payer's money runs out). An
  -- accept takes no money; the daily pass charges on the day and CLEARS this, which
  -- is the only marker of settled. NULL on every handover that charged at accept and
  -- on every trial-only one, which charge nothing by design.
  collect_at              TIMESTAMPTZ                     NULL,
  -- NOT NULL = the payer who ASKED has been shown how this offer ended (declined,
  -- expired or accepted), so the modal that says so never opens again on any device.
  -- Stamped when they press Done, not when the email went out: an email records that
  -- it was sent, which is not the same as a person having seen it.
  outcome_seen_at         TIMESTAMPTZ                     NULL,
  note                    VARCHAR(500)                    NULL,
  CONSTRAINT subscription_transfer_pkey PRIMARY KEY (id),
  CONSTRAINT fk_st_entity FOREIGN KEY (entity_id)    REFERENCES pettycash_test.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_st_from   FOREIGN KEY (from_user_id) REFERENCES pettycash_test.user (id),
  CONSTRAINT fk_st_to     FOREIGN KEY (to_user_id)   REFERENCES pettycash_test.user (id)
);

-- 2.55 subscription_audit_log
--   payer_before / payer_after are only set by the transfer actions - they record
--   WHO PAYS changing, as opposed to what an entity is subscribed to.
CREATE TABLE pettycash_test.subscription_audit_log (
  id               UUID                              NOT NULL DEFAULT gen_random_uuid(),
  entity_id        UUID                              NOT NULL,
  function_code    pettycash_test.module_code        NOT NULL,
  payer_user_id    UUID                              NOT NULL,
  actor_user_id    UUID                              NULL,
  action           VARCHAR(40)                       NOT NULL,
  phase_before     pettycash_test.subscription_phase NULL,
  phase_after      pettycash_test.subscription_phase NULL,
  app_access_until TIMESTAMPTZ                       NULL,
  extension_amount INTEGER                           NULL,   -- cents
  extension_state  pettycash_test.extension_state    NULL,
  outcome          pettycash_test.audit_outcome      NOT NULL,
  cancel_reason    VARCHAR(500)                      NULL,
  note             VARCHAR(500)                      NULL,
  payer_before     UUID                              NULL,
  payer_after      UUID                              NULL,
  created_at       TIMESTAMPTZ                       NOT NULL DEFAULT now(),
  CONSTRAINT subscription_audit_log_pkey PRIMARY KEY (id),
  CONSTRAINT fk_sal_entity FOREIGN KEY (entity_id)     REFERENCES pettycash_test.entities (id) ON DELETE CASCADE,
  CONSTRAINT fk_sal_payer  FOREIGN KEY (payer_user_id) REFERENCES pettycash_test.user (id),
  CONSTRAINT fk_sal_actor  FOREIGN KEY (actor_user_id) REFERENCES pettycash_test.user (id) ON DELETE SET NULL
);

-- 2.56 subscription_email_log  (dedupe_key is what stops a resend)
CREATE TABLE pettycash_test.subscription_email_log (
  id         UUID         NOT NULL DEFAULT gen_random_uuid(),
  user_id    UUID         NOT NULL,
  event      VARCHAR(40)  NOT NULL,
  dedupe_key VARCHAR(200) NOT NULL,
  recipient  VARCHAR(200) NULL,
  status     VARCHAR(20)  NOT NULL,
  error      VARCHAR(500) NULL,
  created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT subscription_email_log_pkey PRIMARY KEY (id),
  CONSTRAINT uq_sub_email_event_key UNIQUE (event, dedupe_key),
  CONSTRAINT fk_sel_user FOREIGN KEY (user_id) REFERENCES pettycash_test.user (id) ON DELETE CASCADE
);

-- 2.57 terms_consent  (who accepted which version of the Terms, and from where)
CREATE TABLE pettycash_test.terms_consent (
  id            UUID         NOT NULL DEFAULT gen_random_uuid(),
  user_id       UUID         NOT NULL,
  terms_version VARCHAR(32)  NOT NULL,
  document_hash VARCHAR(64)  NOT NULL,
  accepted_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
  source        VARCHAR(32)  NOT NULL,
  ip_address    VARCHAR(45)  NULL,
  user_agent    VARCHAR(512) NULL,
  CONSTRAINT terms_consent_pkey PRIMARY KEY (id),
  CONSTRAINT uq_terms_consent_user_version UNIQUE (user_id, terms_version),
  CONSTRAINT fk_tc_user FOREIGN KEY (user_id) REFERENCES pettycash_test.user (id) ON DELETE CASCADE
);


-- ==================================================================
--  3. updated_at 트리거 부착
-- ==================================================================
DO $$
DECLARE t text;
BEGIN
  FOR t IN
    SELECT unnest(ARRAY[
      'currency_info','user','user_token','role','permission',                -- item 21: no country_info
      'entities','account_info','entity_bill_account_xero','entity_bill_currency',
      'xero_contact_sync','entity_function','entity_function_map','entity_pettycash_settings',
      'sale_info','attachment','report','bill','bill_line','bill_attachment',
      'payment','payment_attachment','xero_bill_sync','xero_bill_sync_payload',
      'xero_report_sync','xero_bank_transfer',                                  -- item 22
      -- section K: only the eight that actually carry updated_at. The append-only
      -- logs (audit, email, invoice_line, consent, transfer, terms) do not.
      'entity_cash_setting','billing_plan','billing_policy','payer_billing_group',
      'entity_billing_group','billing_account_payment_method',
      'entity_module_subscription','user_stripe_customer',
      'subscription_invoice'
    ])
  LOOP
    EXECUTE format(
      'CREATE TRIGGER trg_%1$s_updated BEFORE UPDATE ON pettycash_test.%1$I
         FOR EACH ROW EXECUTE FUNCTION pettycash_test.set_updated_at();', t);
  END LOOP;
END $$;


-- ==================================================================
--  4. 인덱스 (FK 지원 + tracker 뷰 최적화 + 조회 패턴)
-- ==================================================================
CREATE INDEX idx_country_currency         ON pettycash_test.country_info (currency_id);
CREATE INDEX idx_user_token_user          ON pettycash_test.user_token (user_id);
CREATE INDEX idx_entities_country_cur     ON pettycash_test.entities (country_code, currency_id);
CREATE INDEX idx_entities_conn_user       ON pettycash_test.entities (connected_by_user_id);
CREATE INDEX idx_user_entity_entity       ON pettycash_test.user_entity (entity_id);
CREATE INDEX idx_invitation_entity        ON pettycash_test.invitation (entity_id);
CREATE INDEX idx_email_otp_email          ON pettycash_test.email_otp (email);
CREATE INDEX idx_account_entity           ON pettycash_test.account_info (entity_id);
CREATE INDEX idx_eax_account              ON pettycash_test.entity_account_xero (account_id);
CREATE INDEX idx_ebax_entity              ON pettycash_test.entity_bill_account_xero (entity_id);
CREATE INDEX idx_ebc_entity               ON pettycash_test.entity_bill_currency (entity_id);
CREATE INDEX idx_xero_contact_entity      ON pettycash_test.xero_contact_sync (entity_id);
CREATE INDEX idx_cash_currency            ON pettycash_test.cash_info (currency_id);
CREATE INDEX idx_ess_sale                 ON pettycash_test.entity_sale_setting (sale_id);
CREATE INDEX idx_sale_info_type           ON pettycash_test.sale_info (type);
CREATE INDEX idx_attachment_uploader      ON pettycash_test.attachment (uploaded_by);
CREATE INDEX idx_report_sale_report       ON pettycash_test.report_sale (report_id);
CREATE INDEX idx_report_expense_report    ON pettycash_test.report_expense (report_id);
CREATE INDEX idx_rea_expense              ON pettycash_test.report_expense_attachment (report_expense_id);
CREATE INDEX idx_rea_attachment           ON pettycash_test.report_expense_attachment (attachment_id);
CREATE INDEX idx_report_cash_count_report ON pettycash_test.report_cash_count (report_id);
CREATE INDEX idx_report_history_report    ON pettycash_test.report_history (report_id);
CREATE INDEX idx_bill_line_bill           ON pettycash_test.bill_line (bill_id);
CREATE INDEX idx_bill_attachment_bill     ON pettycash_test.bill_attachment (bill_id);
CREATE INDEX idx_payment_bill             ON pettycash_test.payment (bill_id);
CREATE INDEX idx_payment_attachment_pay   ON pettycash_test.payment_attachment (payment_id);
CREATE INDEX idx_bill_audit_bill          ON pettycash_test.bill_audit (bill_id);
CREATE INDEX idx_xbs_bill                 ON pettycash_test.xero_bill_sync (bill_id);
CREATE INDEX idx_xbsl_sync                ON pettycash_test.xero_bill_sync_line (xero_bill_sync_id);
CREATE INDEX idx_xbrl_sync                ON pettycash_test.xero_bill_response_line (xero_bill_sync_id);
CREATE INDEX idx_xbt_report               ON pettycash_test.xero_bank_transaction (sync_report_id);
CREATE INDEX idx_xbtr_report              ON pettycash_test.xero_bank_transfer (sync_report_id);

-- section K: foreign key support for the subscription / billing tables
CREATE INDEX idx_ecs_entity               ON pettycash_test.entity_cash_setting (entity_id);
CREATE INDEX idx_ecs_cash                 ON pettycash_test.entity_cash_setting (cash_id);
CREATE INDEX idx_pbg_user                 ON pettycash_test.payer_billing_group (payer_user_id);
CREATE INDEX idx_bapm_group                ON pettycash_test.billing_account_payment_method (billing_group_id);
CREATE INDEX idx_ebg_entity               ON pettycash_test.entity_billing_group (entity_id);
CREATE INDEX idx_ebg_group                ON pettycash_test.entity_billing_group (billing_group_id);
CREATE INDEX idx_ebcon_entity             ON pettycash_test.entity_billing_consent (entity_id);
CREATE INDEX idx_ems_entity               ON pettycash_test.entity_module_subscription (entity_id);
CREATE INDEX idx_ems_payer                ON pettycash_test.entity_module_subscription (payer_user_id);
CREATE INDEX idx_si_payer                 ON pettycash_test.subscription_invoice (payer_user_id);
CREATE INDEX idx_si_group                 ON pettycash_test.subscription_invoice (billing_group_id);
CREATE INDEX idx_sil_invoice              ON pettycash_test.subscription_invoice_line (invoice_id);
CREATE INDEX idx_sil_entity               ON pettycash_test.subscription_invoice_line (entity_id);
CREATE INDEX idx_st_entity                ON pettycash_test.subscription_transfer (entity_id);
CREATE INDEX idx_sal_entity               ON pettycash_test.subscription_audit_log (entity_id);
CREATE INDEX idx_sel_user                 ON pettycash_test.subscription_email_log (user_id);
CREATE INDEX idx_tc_user                  ON pettycash_test.terms_consent (user_id);
CREATE INDEX idx_entities_last_user       ON pettycash_test.entities (last_accessed_by_user_id);

-- The subscription scheduler sweeps by date every day; these are the two columns
-- it filters on, and without them each pass is a full scan of every subscription.
CREATE INDEX idx_ems_access_until         ON pettycash_test.entity_module_subscription (app_access_until);
CREATE INDEX idx_ems_billed_through       ON pettycash_test.entity_module_subscription (billed_through);
CREATE INDEX idx_pbg_paid_through         ON pettycash_test.payer_billing_group (paid_through);

-- One default card per billing account, enforced rather than merely indexed. A
-- second default is not a slow query, it is an account that cannot say which
-- card it charges. Partial, because every non-default row is unconstrained.
CREATE UNIQUE INDEX uq_bapm_one_default
    ON pettycash_test.billing_account_payment_method (billing_group_id)
 WHERE is_default;

-- The open transfer offer for an entity. UNIQUE, and that is the whole point: the
-- app forbids a second offer while one holds a live claim, and this is what enforces
-- it rather than merely making the check fast. It was declared as a plain index here
-- for three revisions of this file while the live schema had it UNIQUE - the rebase
-- lost the constraint because the models declare it as Index(unique=True) rather
-- than UniqueConstraint, so a comparison at the constraint level cannot see it.
--
-- Partial on the three live-claim states, so a settled offer - accepted, declined,
-- cancelled, expired - does not block the next one.
CREATE UNIQUE INDEX idx_st_entity_open    ON pettycash_test.subscription_transfer (entity_id)
  WHERE status IN ('pending','charging','charged');

-- The handovers whose first charge has not been collected yet. Partial for the same
-- reason as the one above: in steady state this is a handful of rows out of every
-- handover ever made, and a full index on a column that is NULL for nearly all of
-- them is mostly a copy of the table. The daily pass reads exactly this set.
CREATE INDEX ix_subscription_transfer_collect
    ON pettycash_test.subscription_transfer (collect_at)
 WHERE collect_at IS NOT NULL;

-- The other half of the same finding. See the note on subscription_invoice.idempotency_key.
CREATE UNIQUE INDEX idx_si_idempotency_key
  ON pettycash_test.subscription_invoice (idempotency_key);

-- tracker 뷰 전용 커버링/부분 인덱스
CREATE INDEX idx_efm_entity_covering
  ON pettycash_test.entity_function_map (entity_id) INCLUDE (entity_function_id, is_enabled);
CREATE INDEX idx_report_entity_txndate
  ON pettycash_test.report (entity_id, transaction_date DESC);
CREATE INDEX idx_report_entity_published
  ON pettycash_test.report (entity_id, transaction_date DESC)
  WHERE publishing_status = 'completed';
CREATE INDEX idx_bill_entity_covering
  ON pettycash_test.bill (entity_id) INCLUDE (status, published, created_at, updated_at);
CREATE INDEX idx_bill_entity_published
  ON pettycash_test.bill (entity_id, updated_at DESC)
  WHERE published = 'published';


-- ==================================================================
--  5. VIEWS
-- ==================================================================

-- report_cash_summary - what report.actual_cash_total used to be, computed from
-- the rows it was always a total of.
--
--   actual_cash_total   the counted cash: quantity x face value, summed over the
--                       denominations counted on that report
--   cash_balance        that plus whatever is in the safe box, which is the
--                       number the Ending page shows and calls the cash balance
--
-- WHY THIS IS A VIEW AND NOT A COLUMN. The column was written once, by one
-- request (report/routes/cash_count.py:361), from the LIVE cash_info values -
-- while every reader of the same quantity, get_cash_count_total()
-- (report/services/cash_denominations.py:163-182), summed the SNAPSHOTTED
-- report_cash_count.cash_value instead. Two independent derivations of one
-- number, agreeing only because both happened inside the same transaction. The
-- view leaves exactly one.
--
-- NULL IS LOAD-BEARING HERE, AND IS NOT ZERO. save_cash_count_details
-- (cash_denominations.py:203-221) DELETES the row for a denomination counted as
-- zero, so a report counted as all-zero legitimately has no rows - and so does a
-- report nobody ever counted. The LEFT JOIN keeps those two apart: no rows means
-- actual_cash_total IS NULL, which is the same "was this counted at all" signal
-- that report.actual_cash_total IS NOT NULL used to carry at ending.py:651 and
-- :1290 and at cash_denominations.py:279-288. A SUM in an unconditional join
-- would have quietly turned both into 0.
--
-- cash_balance is NULL on those same rows, deliberately. The fallback for a
-- report with no count - showing closing_balance instead - is a decision about
-- what to DISPLAY (ending.py:653-659), so it stays in the application rather
-- than being baked in here where the "never counted" case would become
-- indistinguishable from a counted zero all over again.
--
-- safe_box_balance is COALESCEd because it is genuinely optional: a report can
-- have a cash count and no safe box, and that is a balance of the cash counted,
-- not an unknown.
CREATE VIEW pettycash_test.report_cash_summary AS
SELECT r.id                                      AS report_id,
       c.total                                   AS actual_cash_total,
       c.total + COALESCE(r.safe_box_balance, 0) AS cash_balance
  FROM pettycash_test.report r
  LEFT JOIN (SELECT report_id,
                    SUM(quantity * cash_value) AS total
               FROM pettycash_test.report_cash_count
              GROUP BY report_id) c
    ON c.report_id = r.id;

COMMENT ON VIEW pettycash_test.report_cash_summary IS
  'Replaces report.actual_cash_total. NULL actual_cash_total means the report '
  'was never cash-counted, which is not the same as counting zero.';

-- tracker: the per-entity activity summary that exists in production (no code
-- reads it; it is queried by hand). Carried across so the schema swap does not
-- drop it, with two changes: report.company -> report.entity_id (the note below
-- always said so) and the module code 'BILL' -> 'PAYMENT_REQUEST' (item 20).
-- The bill vocabulary it filters on (paid / partially_paid / submitted /
-- published) is unchanged by item 18.
CREATE VIEW pettycash_test.tracker AS
SELECT e.name AS "entities.name",
       e.id   AS entity_id,
       EXISTS (SELECT 1 FROM pettycash_test.entity_function_map efm
                JOIN pettycash_test.entity_function ef ON ef.id = efm.entity_function_id
               WHERE efm.entity_id = e.id AND ef.function_code = 'PETTY_CASH' AND efm.is_enabled) AS pettycash,
       EXISTS (SELECT 1 FROM pettycash_test.entity_function_map efm
                JOIN pettycash_test.entity_function ef ON ef.id = efm.entity_function_id
               WHERE efm.entity_id = e.id AND ef.function_code = 'PAYMENT_REQUEST' AND efm.is_enabled) AS billing,
       rpt.pc_latest_submitted,
       rpt.pc_latest_published,
       bil.num_paid, bil.num_partialpaid, bil.num_unpaid, bil.num_published,
       bil.latest_bill_published, bil.latest_bill_update
  FROM pettycash_test.entities e
  LEFT JOIN LATERAL (
        SELECT max(r.transaction_date) AS pc_latest_submitted,
               max(r.transaction_date) FILTER (WHERE r.publishing_status = 'completed') AS pc_latest_published
          FROM pettycash_test.report r
         WHERE r.entity_id = e.id) rpt ON true
  LEFT JOIN LATERAL (
        SELECT count(*) FILTER (WHERE b.status = 'paid')            AS num_paid,
               count(*) FILTER (WHERE b.status = 'partially_paid')  AS num_partialpaid,
               count(*) FILTER (WHERE b.status = 'submitted')       AS num_unpaid,
               count(*) FILTER (WHERE b.published = 'published')    AS num_published,
               max(b.updated_at) FILTER (WHERE b.published = 'published') AS latest_bill_published,
               greatest(max(b.updated_at), max(b.created_at))       AS latest_bill_update
          FROM pettycash_test.bill b
         WHERE b.entity_id = e.id) bil ON true;

-- ==================================================================
--  참고: tracker 뷰는 위에서 report.entity_id 기준으로 다시 정의했다.
--  Django 프레임워크 테이블(auth_*, django_content_type, django_migrations,
--        sessions)은 본 스크립트에서 제외 — 프레임워크 마이그레이션이 관리.
-- ==================================================================