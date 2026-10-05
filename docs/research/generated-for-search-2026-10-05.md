# Research: generated text that serves search, screened on the fiction, 2026-10-05

**Question.** Plan GS (`docs/plans/generated-for-search-2026-10-05.md`). The LLM's summaries and
diagram descriptions crowd out answers, and were left out of `rag/` (ADR-0028). Would they earn
their place with a request for what a package or diagram is about and for, in other words than
its names? Does more context help? Can the answer's class sort the helpful from the crowding?

**Method.**
- **Four variants** of the requests (`prompts.VARIANTS`):
  - `current/plain`: the requests in use;
  - `current/context`: the same, with context;
  - `about/plain`: what the package or diagram is about and for, in everyday words, with no
    names, identifiers or exact values, after a first line `Class: <class>`;
  - `about/context`: both.
- **The context:**
  - for a package: the packages around it, with what their documentation says first, and the
    documented elements outside it that its elements refer to most;
  - for a diagram: its context element, and each shape's first sentence and a state's behaviors.
- **A tree of the fiction alone per variant** (7 projects), each a copy of `current/plain`'s, so
  that every variant has the same calibration and the same 59 sketches; only the requests differ.
  About 140 requests per variant, on gemma-4-31B-it.
- **Retrieval:** each variant's generated chunks in `rag/`, against `rag/` without them (the
  default, ADR-0028); e5-large without prefixes, BM25 and their fusion, each reranked by Qwen3's
  0.6B reranker. **246 questions:**
  - the 226 standing ones;
  - the 8 list questions;
  - 12 new questions about where something is described (`fiction.where()`): "Where is the
    procedure for washing out a dirty filter at the water works?", graded by element (a window
    of the behavior or package, or its diagram, answers).

## Results

**By question set,** MRR@10 for e5-large reranked / e5-large + BM25 reranked; \* significant.

| Variant | Where-is (12) | Lists (8) | Standing (226) |
|---|---|---|---|
| No generated chunks (the default) | 0.647 / 0.583 | 0.812 / 0.708 | 0.798 / 0.791 |
| `current/plain` | 0.760 / 0.677 | 0.906 / 0.906 | 0.758\* / 0.764\* |
| `current/context` | 0.758 / 0.718 | 0.906 / 0.823 | 0.772\* / 0.775 |
| `about/plain` | 0.743 / 0.722\* | 0.917 / 0.823 | 0.781\* / 0.777\* |
| `about/context` | 0.790\* / 0.814\* | 0.917 / 0.823 | 0.785\* / 0.783 |

- **Where-is questions** are what generated chunks are for, and every variant helps them;
  `about/context` the most: hit@10 for the hybrid, reranked, 0.75 → 1.00.
- **Standing questions** lose with every variant, but `about/context` loses least: a third of
  `current/plain`'s loss for e5-large reranked, and not significant for the hybrid, reranked.
- **Context** changed little with the requests in use: their answers stay inventories of names,
  and the context goes unused (the kiosk's Jammed state pages the librarian; its description
  still doesn't say so). With the `about` request, context raised the where-is gain
  (0.722 → 0.814).

**What the answers look like.** The Harbour Road corridor's first part:
- `current/plain`: "These sites include Harbour Road & Abbot Lane, Harbour Road & Brindle Street,
  … and controllers like Meridian ATC-4 or Meridian ATC-5."
- `about/context`: "This part lists specific traffic signal intersections along a single road
  corridor. It provides the physical configuration and hardware inventory for each site … It also
  records administrative details such as site identifiers, cabinet locations, ward assignments,
  commissioning dates, and current firmware versions …"

The Filter Backwash Sequence, `about/context`: "This diagram describes the operational sequence
for cleaning a filter in a water treatment plant …"

**Classes don't sort them.**
- **The spread** (`about/context`): structure 52, requirements 37, register 34, flow 10,
  states 4, behavior 3, intent 1.
- **Unstable:** the Equipment Catalogue was `library` without context and `register` with it.
- **Leaving classes out** costs the where-is gain more than it saves the standing questions:

  | `about/context`, classes left out | Where-is | Standing |
  |---|---|---|
  | none | 0.790 / 0.814 | 0.785 / 0.783 |
  | register | 0.748 / 0.676 | 0.785 / 0.785 |
  | register, requirements | 0.747 / 0.669 | 0.788 / 0.786 |
  | register, requirements, structure | 0.750 / 0.689 | 0.791 / 0.784 |

- **What still crowds** (`about/context`): 10 standing questions rank lower and 2 higher, nearly
  all paraphrases. Above their answers are diagram descriptions on the right topic without the
  fact: for "When does a filter at the water works need cleaning?", the backwash procedure's
  description ranks above the filter's state machine.

**By kind** (`about/context`): package summaries alone cost the standing questions nothing
(0.795 / 0.791) and help where-is questions a little (0.649 / 0.653); diagram descriptions alone
help more (0.750 / 0.689) and cost a little (0.790 / 0.786). Together they help most.

## A reading on real models (GS-06)

The drone and SAF_FFDS, built with the requests in use and with `about/context` (173 new answers;
`out/gs3/reading.txt`): 20 package answers and 20 diagram answers drawn at random, each read
beside its input, its context and the answer in use.
- **Package answers: 20 of 20 faithful.** Each says what the package covers and what it is for,
  where the answer in use lists names. "This package contains the safety assurance case for the
  forest fire detection system", for one whose answer in use names each claim and argument. The
  strongest stretch: "ensuring the drone can safely navigate".
- **Diagram answers: 19 of 20 faithful in substance.**
  - **One misreading:** a maintainer's activity returns "a fire department system" to operation,
    where the system is the FFDS and the fire department only a swimlane.
  - **Generic purposes:** several end with a purpose the input doesn't state ("This ensures that
    every system requirement is justified by an operational need", "to save a life"): inferred,
    as the request allows, and general.
- **The classes on real models:** structure 67, flow 20, interfaces 18, overview 17, behavior 16,
  intent 13, requirements 13, library 6, states 2, sparse 1.
- **Context:** the model's own documentation is sometimes noise (an ONVIF specification pasted
  into data types, a sentence in German); the answers ignore it.

## The release check (GS-07, 0.20.0)

The whole tree (the samples and the fiction) built with `about/context` (`out/v020/on`: 4,084 new
answers, 59 minutes; the invariants hold; 5,349 summaries and descriptions, every one with a valid
class: requirements 1,435, flow 1,303, structure 1,288, behavior 370, intent 257, interfaces 127,
register 119, library 116, overview 109, results 107, states 106, sparse 12). Retrieval on the 246
questions, MRR@10 for e5-large reranked / e5-large + BM25 reranked; \* significant against 0.19.1:

| `rag/` | Where-is (12) | Lists (8) | Standing (226) |
|---|---|---|---|
| 0.19.1: no generated summaries or descriptions | 0.647 / 0.593 | 0.812 / 0.729 | 0.792 / 0.793 |
| 0.19.0: the requests before | 0.760 / 0.719 | 0.906 / 0.792 | 0.753\* / 0.759\* |
| 0.20.0: package summaries only | 0.649 / 0.653 | 0.792 / 0.698 | 0.787\* / 0.785\* |
| 0.20.0: diagram descriptions only | 0.750 / 0.694\* | 0.938 / 0.854 | 0.783\* / 0.787\* |
| 0.20.0: both | 0.790\* / 0.772\* | 0.917 / 0.781 | 0.778\* / 0.780\* |

- **Against 0.19.0,** 0.20.0 is better wherever the change is significant: the standing questions
  gain 0.025 / 0.021.
- **Against 0.19.1,** the where-is questions gain greatly (hit@10 0.83 → 1.00 for the hybrid), and
  the standing questions lose a little, significantly, on the whole tree (0.013 / 0.014; hit@10
  0.942 → 0.934, not significant). On the fiction alone, the hybrid's loss wasn't significant.
- **By kind,** each costs the standing questions a little and the costs add up; the where-is
  gains are larger together than apart.

## Caveats

- **12 where-is questions** are few; the gain is significant, its size uncertain.
- **The fiction alone:** the samples weren't there as distractors.
- **One model,** gemma-4-31B-it, and a reading of 40 answers on two models.

## Decision

The maintainer, 2026-10-05: "Yes, about should replace summaries. Please proceed with the
experiment." After the reading, `about/context` becomes the requests in use, on the pages; the
classes stay in the metadata. Whether its answers enter `rag/`, given the release check's small
cost to the standing questions, went back to the maintainer (plan GS, "When to stop and ask").
