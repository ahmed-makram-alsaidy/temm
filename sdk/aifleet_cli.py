import argparse
import asyncio
import json
import sys

from aifleet_sdk import AiFleetClient, AiFleetSdkError, AiFleetValidationError, require_goal


def parser():
    value = argparse.ArgumentParser(prog="aifleet")
    value.add_argument("--base-url", default="http://127.0.0.1:8787")
    value.add_argument("--json", action="store_true")
    sub = value.add_subparsers(dest="group", required=True)
    projects = sub.add_parser("project").add_subparsers(dest="action", required=True)
    projects.add_parser("list")
    # Declared optional to argparse so a missing goal is reported the same way as every
    # other refusal - one structured error and exit 2 - instead of argparse's usage text,
    # which is unparseable for a caller running with --json. The requirement itself is
    # enforced by `require_goal`, which is also what the SDK enforces, so there is one
    # rule rather than two that can drift.
    create = projects.add_parser("create"); create.add_argument("name"); create.add_argument("slug"); create.add_argument("--goal", default="", help="What you want TEMM to accomplish. Required."); create.add_argument("--type", default="software")
    runs = sub.add_parser("run").add_subparsers(dest="action", required=True)
    show = runs.add_parser("inspect"); show.add_argument("id")
    cancel = runs.add_parser("cancel"); cancel.add_argument("id")
    workflow = sub.add_parser("workflow").add_subparsers(dest="action", required=True)
    for action in ["status", "pause", "resume", "cancel"]: command = workflow.add_parser(action); command.add_argument("id")
    inspect = sub.add_parser("inspect"); inspect.add_argument("resource", choices=["fleet"])
    return value


async def execute(args, client):
    if args.group == "project" and args.action == "list": return [item.__dict__ for item in await client.list_projects()]
    if args.group == "project" and args.action == "create": return (await client.create_project(args.name, args.slug, args.type, args.goal)).__dict__
    if args.group == "run" and args.action == "inspect": return (await client.get_run(args.id)).__dict__
    if args.group == "run" and args.action == "cancel": return await client.cancel_run(args.id)
    if args.group == "inspect": return await client.fleet_overview()
    path = f"/api/orchestrations/{args.id}" if args.action == "status" else f"/api/orchestrations/{args.id}/{args.action}"
    return await client.request("GET" if args.action == "status" else "POST", path, **({} if args.action == "status" else {"json": {"payload": {}}}))


async def async_main(argv=None, client=None):
    args = parser().parse_args(argv)
    owned = client is None
    client = client or AiFleetClient(args.base_url)
    try:
        # Checked before the connection so an invocation that could never be valid is
        # answered as the missing goal it is, rather than as whatever the network says
        # first. A headless command never prompts for it.
        if args.group == "project" and args.action == "create": require_goal(args.goal)
        await client.negotiate()
        result = await execute(args, client)
        print(json.dumps(result, default=str) if args.json else result)
        return 0
    except AiFleetValidationError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": str(exc)}}) if args.json else f"error: {exc.code}: {exc}", file=sys.stderr)
        return 2
    except AiFleetSdkError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": str(exc)}}) if args.json else f"error: {exc.code}: {exc}", file=sys.stderr)
        return 2
    finally:
        if owned: await client.close()


def main(): raise SystemExit(asyncio.run(async_main()))
