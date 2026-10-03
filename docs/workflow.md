Automation Workflow

Overview

The Automated Micro-Influencer Outreach System is designed as an end-to-end pipeline for discovering, evaluating, enriching, personalizing, and preparing outreach for relevant micro-influencers.

The workflow combines YouTube-based influencer discovery, profile enrichment, filtering and classification, AI-generated personalization, human approval, and outreach tracking.

## End-to-End Workflow

```text
YouTube Data API
       |
       v
Influencer Discovery
       |
       v
Candidate Filtering
       |
       v
Profile Enrichment
       |
       v
Classification & Outreach Readiness
       |
       v
AI Personalization
       |
       v
Human Approval
       |
       v
Dry-Run / Email Sending
       |
       +----------------------+
       |                      |
       v                      v
Outreach Tracker       Instagram DM Queue
```

## 1. Influencer Discovery

The system searches YouTube using multiple configured niche-related search queries.

The current workflow uses queries covering areas such as:

- skincare routine
- makeup tutorial
- fashion haul
- outfit ideas
- beauty review
- get ready with me
- capsule wardrobe
- hair care routine

The discovery module collects candidate YouTube channels and removes duplicate candidates before continuing through the pipeline.

### Actual Run Result

The latest pipeline run discovered:

- 762 unique candidate channels
- 86 channels within the configured follower/subscriber range

The discovered candidates are saved to:

```text
data/candidates.json
```

## 2. Profile Enrichment

Each in-range candidate is enriched with additional publicly available profile information.

The enrichment stage collects information used by later stages of the pipeline, including profile details, contact information when publicly available, engagement-related information, recent content, and other relevant metadata.

The enriched dataset is saved to:

```text
data/influencers_enriched.csv
```

### Actual Run Result

The latest run successfully enriched:

```text
86 / 86 profiles
```

Of these profiles:

```text
20 profiles had a public email address
```

## 3. Filtering and Classification

The filtering stage evaluates the enriched profiles against the configured criteria.

The system determines whether an influencer matches the campaign requirements and classifies qualifying profiles for outreach.

The filtered results are saved to:

```text
data/influencers_filtered.csv
```

### Actual Run Result

The latest run produced:

```text
52 / 86 profiles passed filtering
15 profiles were outreach-ready with email
```

Profiles without the required information are not treated as outreach-ready.

## 4. AI Personalization

For qualifying influencers, the system generates personalized outreach content using the configured LLM provider.

The personalization stage generates:

- collaboration angle
- email subject
- personalized email body
- Instagram DM

The generated messages are saved to:

```text
data/messages.csv
```

The personalization uses available influencer and content information so that the generated message is specific to the individual profile rather than being a single generic message.

## 5. Human Approval

Before live outreach, the workflow supports a human approval step.

This allows generated messages to be reviewed before they are sent.

The approval stage is intended to prevent automatically generated content from being sent without review.

## 6. Outreach Execution

The system supports a dry-run mode for testing the outreach workflow without sending real emails.

The latest dry-run produced:

```text
Sent: 0
Simulated: 0
Failed: 0
Suppressed: 0
```

The outreach log showed:

```text
SIMULATED: 16
SKIPPED_NO_EMAIL: 40
```

The results are tracked in:

```text
data/outreach_tracker.csv
```

## 7. Instagram DM Queue

Instagram messages are not automatically sent by the email workflow.

Instead, the system prepares Instagram outreach messages for manual sending.

The generated queue is saved to:

```text
data/dm_queue.csv
```

This separates message generation from manual Instagram execution.

## 8. Outreach Tracking

The system maintains an outreach tracker to record the status of outreach operations.

The tracker provides a persistent record of processed outreach actions and helps prevent unnecessary duplicate processing.

The tracker is stored in:

```text
data/outreach_tracker.csv
```

## 9. Output Files

The main generated outputs are:

```text
data/
├── influencers_enriched.csv
├── influencers_filtered.csv
├── messages.csv
├── outreach_tracker.csv
└── dm_queue.csv
```

These files provide the main artifacts produced by the pipeline.

## 10. Complete Pipeline Summary

The complete workflow can be summarized as:

```text
Discover
   ↓
Deduplicate
   ↓
Filter by configured range
   ↓
Enrich profiles
   ↓
Evaluate and classify
   ↓
Identify outreach-ready influencers
   ↓
Generate personalized email + Instagram DM
   ↓
Human approval
   ↓
Dry-run / email execution
   ↓
Track outreach
   ↓
Prepare Instagram DM queue
```

The latest demonstrated run processed real influencer data through the pipeline, producing enriched profiles, filtered candidates, personalized outreach content, an outreach tracker, and an Instagram DM queue.