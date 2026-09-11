#!/usr/bin/env python3
"""Fail closed unless the GitHub signing environment is explicitly protected."""
import json
import os
import urllib.request


def validate(environment: dict, policies: dict, branch: dict) -> None:
    rules = environment.get("protection_rules", [])
    if not any(rule.get("type") == "required_reviewers" and rule.get("reviewers") for rule in rules):
        raise ValueError("firmware-signing requires a release reviewer")
    if environment.get("can_admins_bypass") is not False:
        raise ValueError("disable administrator bypass for firmware-signing")
    if environment.get("deployment_branch_policy") != {
            "protected_branches": False, "custom_branch_policies": True}:
        raise ValueError("use an exact main-branch environment policy")
    allowed = policies.get("branch_policies", [])
    if len(allowed) != 1 or allowed[0].get("name") != "main" or allowed[0].get("type") != "branch":
        raise ValueError("firmware-signing must allow only the main branch")
    if branch.get("protected") is not True:
        raise ValueError("protect main before enabling release signing")


def main():
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise SystemExit("signing must run from main")
    repository = os.environ["GITHUB_REPOSITORY"]
    def get(suffix):
        request = urllib.request.Request(f"https://api.github.com/repos/{repository}/{suffix}",
            headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                     "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    validate(get("environments/firmware-signing"),
             get("environments/firmware-signing/deployment-branch-policies"), get("branches/main"))
    print("Protected signing environment verified")


if __name__ == "__main__":
    main()
