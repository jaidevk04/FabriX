"""Local server and reproducible scenario-matrix CLI."""

import argparse
import asyncio
import json
import os
import sys

from cognition.config import load_environment
from cognition.domain import Industry, PlantSpec
from cognition.harnesses.factory import create
from cognition.persistence.store import Store
from cognition.runtime.platform import Platform
from cognition.simulation.thermal import Scenario


async def demo(name: str) -> None:
    store = Store()
    platform = Platform(store)
    try:
        harness = create(name)
        result = []
        scenarios: list[Scenario] = ["heat_load", "actuator_stuck", "sensor_fault"]
        for industry in Industry:
            for scenario in scenarios:
                plant_id = f"{industry}-{scenario}"
                platform.onboard(PlantSpec(id=plant_id, name=plant_id, industry=industry))
                platform.connector.disturb(plant_id, scenario)
                incident = await platform.resolve(plant_id, harness)
                result.append(
                    {
                        "industry": industry,
                        "scenario": scenario,
                        "status": incident.status,
                        "reason": incident.reason,
                    }
                )
        print(json.dumps(result, indent=2))
    finally:
        store.close()


def evaluate(args: argparse.Namespace) -> int:
    """Play the demo stories on an in-memory platform and report measured results."""
    from cognition.evaluation.stories import STORIES
    from cognition.evaluation.suite import run_all

    if args.list:
        for story in STORIES.values():
            print(f"{story.id:<24} {story.industry:<9} {story.title}")
        return 0
    live = args.harness != "reference" or args.agents
    if live and not args.yes:
        print(
            "This run would call a live model and can incur charges. Repeat with --yes to confirm.",
            file=sys.stderr,
        )
        return 2
    try:
        results = asyncio.run(run_all(args.scenario, args.harness, agents=args.agents))
    except KeyError as error:
        print(error.args[0], file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        for result in results:
            print(f"{'PASS' if result['passed'] else 'FAIL'}  {result['story']}: {result['title']}")
            for check in result["checks"]:
                print(f"      {'ok ' if check['ok'] else 'BAD'} {check['name']}: {check['detail']}")
    return 0 if all(r["passed"] for r in results) else 1


def story(args: argparse.Namespace) -> int:
    """List stories or play one against a running server."""
    import httpx

    from cognition.evaluation.stories import STORIES, run_story

    if args.action == "list":
        for item in STORIES.values():
            print(f"{item.id:<24} {item.industry:<9} {item.title}")
        return 0
    chosen = STORIES.get(args.id or "")
    if chosen is None:
        print(f"Unknown story. Available: {', '.join(STORIES)}", file=sys.stderr)
        return 2
    plant = args.plant or f"{chosen.industry}-demo"
    try:
        with httpx.Client(base_url=args.api, timeout=10) as client:
            run_story(client, chosen, plant)
    except httpx.HTTPError as error:
        print(
            f"Could not play the story against {args.api}: {type(error).__name__}", file=sys.stderr
        )
        return 1
    return 0


def main() -> None:
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    server = commands.add_parser("serve")
    server.add_argument("--port", type=int, default=int(os.getenv("COGNITION_PORT", "8000")))
    server.add_argument("--host", default=os.getenv("COGNITION_HOST", "127.0.0.1"))
    matrix = commands.add_parser("demo")
    matrix.add_argument("--harness", default="reference")
    commands.add_parser("mcp")
    check = commands.add_parser("evaluate", help="Run the offline evaluation scenarios.")
    check.add_argument("--scenario")
    check.add_argument("--list", action="store_true")
    check.add_argument("--json", action="store_true")
    check.add_argument("--harness", default="reference")
    check.add_argument("--agents", action="store_true", help="Run the ADK core agents (live).")
    check.add_argument("--yes", action="store_true", help="Confirm a live, billable run.")
    play = commands.add_parser("story", help="Play a demo story against a running server.")
    play.add_argument("action", choices=["list", "run"])
    play.add_argument("id", nargs="?")
    play.add_argument("--api", default=os.getenv("COGNITION_API_URL", "http://127.0.0.1:8000"))
    play.add_argument("--plant")
    args = parser.parse_args()
    if args.command == "evaluate":
        sys.exit(evaluate(args))
    if args.command == "story":
        sys.exit(story(args))
    if args.command == "serve":
        import uvicorn

        if args.host not in ("127.0.0.1", "localhost", "::1"):
            print(
                f"Listening on {args.host}:{args.port}. The API has no authentication: "
                "put it behind an authenticating reverse proxy or a private network.",
                file=sys.stderr,
            )
        uvicorn.run("cognition.api:app", host=args.host, port=args.port)
    elif args.command == "mcp":
        from cognition.mcp.server import main as mcp_main

        mcp_main()
    else:
        asyncio.run(demo(args.harness))


if __name__ == "__main__":
    main()
