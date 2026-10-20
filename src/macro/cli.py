import argparse
import json

from macro.shared.io import read_json


def main():
    parser = argparse.ArgumentParser(description="MACRO Part 1. Evaluation uses real AG2 judges and requires explicit paid-API acknowledgement.")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit", help="Offline streaming source audit and seeded recipe subset")
    audit.add_argument("--source", default="pp_recipes/pp_recipes.csv")
    audit.add_argument("--out", default="data/subset")
    generate = sub.add_parser("generate", help="Offline pilot generation, exactly 20 cases")
    generate.add_argument("--subset", default="data/subset")
    generate.add_argument("--out", default="data/pilot")
    validate = sub.add_parser("validate", help="Offline reference and schema checks")
    validate.add_argument("--cases", default="data/pilot")
    for name in ["run", "plan"]:
        p = sub.add_parser(name, help="Evaluate with real AG2 judges (paid API calls)" if name == "run" else "No-cost request-count preview")
        p.add_argument("--cases", default="data/pilot")
        p.add_argument("--limit", type=int, default=20)
        p.add_argument("--split", choices=["dev", "test"], help="Explicit benchmark split; --cases must be its root. Final-test execution awaits review/freeze.")
        if name == "run":
            # Accept previously documented commands; every run now uses real judges.
            p.add_argument("--live", action="store_true", help=argparse.SUPPRESS)
            p.add_argument("--allow-paid-api", action="store_true")
            p.add_argument("--run-id")
            p.add_argument("--max-calls", type=int, default=240)
            p.add_argument("--retry-uncertain", action="store_true")
    summary = sub.add_parser("summarize", help="Rebuild metrics and Markdown/HTML reports from a saved run, without API calls")
    summary.add_argument("run_dir")
    for p in [audit, generate, sub.choices["run"], sub.choices["plan"]]:
        p.add_argument("--config", default="configs/pilot.json")
    args = parser.parse_args()
    try:
        if args.command in ["audit", "generate", "validate"]:
            from macro.evaluate_case_generation.source_audit import audit
            from macro.evaluate_case_generation.cases import generate, validate
            if args.command == "audit":
                audit(args.source, args.out, read_json(args.config))
            elif args.command == "generate":
                generate(args.subset, args.out, read_json(args.config))
            else:
                validate(args.cases)
        elif args.command == "summarize":
            from macro.reporting.summary import summarize
            print(json.dumps(summarize(args.run_dir), indent=2))
        else:
            from macro.evaluation.runner import experiment_plan, run
            config = read_json(args.config)
            if args.command == "plan":
                print(json.dumps(experiment_plan(args.cases, args.limit, config, args.split), indent=2))
            else:
                if not args.allow_paid_api:
                    parser.error("Evaluation uses real AG2 judges and incurs API costs. Add --allow-paid-api to run.")
                run(args.cases, config, args.limit, args.run_id, args.max_calls, args.retry_uncertain, args.split)
    except (ValueError, AssertionError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
