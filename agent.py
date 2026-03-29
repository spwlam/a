#!/usr/bin/env python3
"""
Candidate Role Filtering Agent

Evaluates financial advisor job opportunities against a specific candidate profile
to identify roles that best advance toward a high-producing advisor career in NYC.

Usage:
    # Evaluate roles from a JSON file
    python agent.py --file roles.json

    # Evaluate a single role interactively
    python agent.py --interactive

    # Evaluate roles from stdin (JSON)
    echo '[{"title": "...", "company": "...", "description": "..."}]' | python agent.py
"""

import anthropic
import argparse
import json
import os
import sys
from typing import List, Optional
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Candidate profile & filtering rules (encoded once, cached by the model)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a career advisor specializing in financial services, specifically in evaluating
job opportunities for financial advisors transitioning from service roles to production roles in NYC.

## CANDIDATE PROFILE

The candidate has:
- Series 7 and Series 66 licenses
- Experience as an Associate Advisor at LPL Financial (Wealth Advisors Group)
- Skills in: client service, investment conversations, financial planning

## CAREER GOAL

Transition from associate/service advisor → producing advisor.
Leverage NYC location for higher net worth client exposure.
Accelerate path to high income (VP Financial Consultant or equivalent).

## EVALUATION FRAMEWORK

### STRICT FILTER — DO NOT PRIORITIZE roles that are:
- Equivalent to pure service/support roles (no client ownership, no book)
- Clearly below current experience level (entry-level training programs)
- Lacking investment or advisory exposure
- Admin-heavy with no path to production

### PRIORITIZE roles that:
- Allow immediate contribution (no entry-level training required)
- Involve client interaction and advisory conversations
- Provide opportunity for asset gathering and client ownership
- Represent a step FORWARD (service → production, not lateral or backward)
- Transition from service → production
- Offer exposure to higher net worth or ultra-high-net-worth clients
- Are based in NYC with in-person client interaction

### RIA QUALITY SCORING — Score higher if:
- Firm has strong inbound pipeline or referral system
- Firm serves HNW/UHNW clients
- Advisors grow into revenue-producing roles
- Compensation supports long-term upside (payout/equity)

Flag as red flags if:
- Role appears admin-heavy
- Advisor is just supporting without a growth path
- Firm lacks deal flow or client acquisition channels

### CAREER PROGRESSION TEST
For every role ask: "Does this move the candidate closer to becoming a high-producing advisor in NYC?"
- YES → prioritize
- NO → downgrade or ignore

## SCORING RUBRIC (1–10)

10 — Perfect fit: producing role, HNW clients, NYC, strong inbound, immediate contribution
8–9 — Strong: clear path to production, HNW exposure, good firm quality
6–7 — Decent: some growth path but not ideal (mixed service/production, or lower AUM tier)
4–5 — Lateral/marginal: service-heavy but some advisory exposure
1–3 — Do not pursue: pure service, below current level, no growth path

## RECOMMENDATION LABELS
- PRIORITIZE — Score 8+, strong career acceleration
- CONSIDER    — Score 6–7, viable with caveats
- DOWNGRADE   — Score 4–5, lateral or marginal step
- IGNORE      — Score 1–3, below current level or no growth path

Be direct and opinionated. This candidate has real credentials and should not waste time on lateral moves."""


# ---------------------------------------------------------------------------
# Pydantic schemas for structured output
# ---------------------------------------------------------------------------

class RoleEvaluation(BaseModel):
    role_title: str
    company: str
    score: int
    recommendation: str          # PRIORITIZE | CONSIDER | DOWNGRADE | IGNORE
    rationale: str
    career_progression: str      # How/whether this moves toward high-producing advisor
    green_flags: List[str]
    red_flags: List[str]
    compensation_notes: str
    client_quality: str          # HNW/UHNW/Mass Affluent/Retail/Unknown


class FilteringResult(BaseModel):
    evaluations: List[RoleEvaluation]
    top_pick: Optional[str]       # Role title + company of the single best option
    summary: str                  # 2–3 sentence executive summary of the batch


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class CandidateFilteringAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )

    def evaluate(self, roles: List[dict]) -> FilteringResult:
        """
        Evaluate a list of roles against the candidate's profile.

        Each role dict should have:
            title       (str, required)  — job title
            company     (str, required)  — firm name
            description (str, required)  — full job description or summary
            location    (str, optional)  — defaults to assumed NYC if omitted
        """
        if not roles:
            raise ValueError("At least one role is required.")

        roles_text = "\n\n".join(
            f"### Role {i + 1}: {r.get('title', 'Untitled')} at {r.get('company', 'Unknown')}\n"
            f"Location: {r.get('location', 'Not specified')}\n\n"
            f"{r.get('description', '').strip()}"
            for i, r in enumerate(roles)
        )

        user_message = (
            f"Please evaluate the following {len(roles)} role(s) for the candidate "
            f"described in your system prompt. Apply all filtering criteria strictly.\n\n"
            f"{roles_text}"
        )

        response = self.client.messages.parse(
            model="claude-opus-4-6",
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            output_format=FilteringResult,
        )

        if response.parsed_output is None:
            raise RuntimeError(
                f"Model failed to return structured output "
                f"(stop_reason={response.stop_reason}). "
                "Try reducing the number of roles per batch or increasing max_tokens."
            )

        return response.parsed_output

    def print_results(self, result: FilteringResult) -> None:
        """Pretty-print evaluation results to stdout."""
        LABEL_COLORS = {
            "PRIORITIZE": "\033[92m",   # green
            "CONSIDER":   "\033[93m",   # yellow
            "DOWNGRADE":  "\033[33m",   # dark yellow
            "IGNORE":     "\033[91m",   # red
        }
        RESET = "\033[0m"
        BOLD  = "\033[1m"

        print(f"\n{'=' * 70}")
        print(f"{BOLD}CANDIDATE ROLE FILTERING REPORT{RESET}")
        print(f"{'=' * 70}")

        # Sort: highest score first
        sorted_evals = sorted(result.evaluations, key=lambda e: e.score, reverse=True)

        for ev in sorted_evals:
            color = LABEL_COLORS.get(ev.recommendation, "")
            print(f"\n{BOLD}{ev.role_title}{RESET}  —  {ev.company}")
            print(f"  Score:          {BOLD}{ev.score}/10{RESET}")
            print(f"  Recommendation: {color}{BOLD}{ev.recommendation}{RESET}")
            print(f"  Client Quality: {ev.client_quality}")
            print(f"  Compensation:   {ev.compensation_notes}")
            print(f"  Progression:    {ev.career_progression}")
            print(f"  Rationale:      {ev.rationale}")

            if ev.green_flags:
                print(f"  {BOLD}Green Flags:{RESET}")
                for flag in ev.green_flags:
                    print(f"    ✓ {flag}")

            if ev.red_flags:
                print(f"  {BOLD}Red Flags:{RESET}")
                for flag in ev.red_flags:
                    print(f"    ✗ {flag}")

        print(f"\n{'─' * 70}")
        if result.top_pick:
            print(f"{BOLD}TOP PICK:{RESET} {result.top_pick}")
        print(f"\n{BOLD}SUMMARY:{RESET}")
        print(f"  {result.summary}")
        print(f"{'=' * 70}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_roles_from_file(path: str) -> List[dict]:
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "roles" in data:
        return data["roles"]
    raise ValueError("JSON file must be a list of roles or {\"roles\": [...]}")


def interactive_mode() -> List[dict]:
    print("Enter role details (empty title to finish):\n")
    roles = []
    while True:
        title = input("  Job title (or Enter to finish): ").strip()
        if not title:
            break
        company = input("  Company: ").strip()
        location = input("  Location [NYC]: ").strip() or "NYC"
        print("  Job description (paste, then enter a line with just '---'):")
        lines = []
        while True:
            line = input()
            if line.strip() == "---":
                break
            lines.append(line)
        roles.append({
            "title": title,
            "company": company,
            "location": location,
            "description": "\n".join(lines),
        })
        print()
    return roles


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate financial advisor job opportunities for a Series 7/66 candidate."
    )
    parser.add_argument("--file", "-f", help="Path to JSON file containing roles")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Enter roles interactively")
    parser.add_argument("--output", "-o", choices=["text", "json"], default="text",
                        help="Output format (default: text)")
    args = parser.parse_args()

    # Determine input source
    if args.file:
        roles = load_roles_from_file(args.file)
    elif args.interactive:
        roles = interactive_mode()
    elif not sys.stdin.isatty():
        roles = json.load(sys.stdin)
        if isinstance(roles, dict) and "roles" in roles:
            roles = roles["roles"]
    else:
        parser.print_help()
        sys.exit(0)

    if not roles:
        print("No roles provided. Exiting.")
        sys.exit(0)

    agent = CandidateFilteringAgent()

    print(f"\nEvaluating {len(roles)} role(s)...", file=sys.stderr)
    result = agent.evaluate(roles)

    if args.output == "json":
        print(result.model_dump_json(indent=2))
    else:
        agent.print_results(result)


if __name__ == "__main__":
    main()
