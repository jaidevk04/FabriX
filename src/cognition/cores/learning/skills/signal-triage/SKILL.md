---
name: signal-triage
description: Rank which sensor channels and equipment deviate and decide what to look at first. Use at the start of every learning analysis, before diagnosing or estimating remaining life.
---

# Signal triage

## Procedure

1. Call `learning_read_encoder_scores` with no filter. Note the top three channels and their tokens.
2. Group them by equipment. Several channels on one equipment item agree more than one channel alone.
3. For the top equipment, call `learning_list_channels` with that equipment to see raw status next to the scores.
4. Mask nothing and change nothing. Triage only reads.

## Reading scores

- A score under 0.25 is noise for this prototype. Between 0.25 and 0.5 is a watch. Above 0.75 deserves a diagnosis.
- Steady tokens on a channel that was high a moment ago mean the condition may be passing. Say so.
