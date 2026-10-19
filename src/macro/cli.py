"""Commands for the current benchmark; paid execution always requires explicit consent."""
import argparse
import json
from pathlib import Path

from macro.shared.io import read_json
from macro.shared.config import provider_config


def main():
    parser = argparse.ArgumentParser(description="MACRO benchmark evaluation with independent AG2 judges.")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit", help="Prepare a versioned HUMMUS subset without API calls")
    audit.add_argument("--source", default="pp_recipes/pp_recipes.csv")
    audit.add_argument("--out", default="data/subset-v1")
    audit.add_argument("--config", default="configs/dataset-v1.json")
    generate = sub.add_parser("generate", help="Generate a benchmark package without API calls; refuses overwrites")
    generate.add_argument("--subset", default="data/subset-v1")
    generate.add_argument("--out", default="data/benchmark-v2")
    generate.add_argument("--config", default="configs/benchmark-v2.json")
    generate.add_argument("--pilot", default="data/pilot/cases.jsonl", help="Historical cases used only to exclude previously inspected recipes")
    validate = sub.add_parser("validate", help="Verify benchmark hashes, labels and development/test separation")
    validate.add_argument("--cases", default="data/benchmark-v2/test")
    for name in ("run", "plan"):
        p = sub.add_parser(name, help="Run AG2 judges using the selected provider" if name == "run" else "Validate inputs and preview request counts (no API calls)")
        p.add_argument("--cases", default="data/benchmark-v2/test")
        p.add_argument("--config", default="configs/benchmark-judges.json")
        p.add_argument("--limit", type=int, help="Number of cases; omitted means the complete selected split")
        if name == "run":
            p.add_argument("--allow-paid-api", action="store_true")
            p.add_argument("--run-id")
            p.add_argument("--max-calls", type=int, help="Required explicit request cap; not a money limit")
            p.add_argument("--retry-uncertain", action="store_true")
    summary = sub.add_parser("summarize", help="Rebuild saved reports without API calls")
    summary.add_argument("run_dir")
    args = parser.parse_args()
    try:
        if args.command == "audit":
            from macro.evaluate_case_generation.dataset import prepare
            prepare(args.source, args.out, read_json(args.config))
        elif args.command == "generate":
            from macro.evaluate_case_generation.benchmark import generate
            generate(args.subset, args.out, read_json(args.config), args.pilot)
        elif args.command == "validate":
            from macro.evaluate_case_generation.benchmark import verify_saved
            folder = Path(args.cases)
            package = folder if (folder / "manifest.json").exists() else folder.parent
            print(json.dumps(verify_saved(package), indent=2))
        elif args.command == "summarize":
            from macro.reporting.summary import summarize
            print(json.dumps(summarize(args.run_dir), indent=2))
        else:
            from macro.evaluation.runner import experiment_plan, run
            config = provider_config(read_json(args.config))
            if args.command == "run":
                if config["provider"] == "openai" and not args.allow_paid_api:
                    parser.error("Evaluation incurs API costs. Add --allow-paid-api to run.")
                if args.max_calls is None:
                    parser.error("Set --max-calls explicitly to cap model requests.")
            if args.command == "plan":
                print(json.dumps(experiment_plan(args.cases, args.limit, config), indent=2))
            else:
                run(args.cases, config, args.limit, args.run_id, args.max_calls, args.retry_uncertain)
    except (ValueError, AssertionError, FileNotFoundError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
