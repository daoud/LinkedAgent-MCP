"""Pre-deploy production checklist.

Validates that the environment is correctly configured before deploying.
Exits with code 1 if any required check fails (when --exit-on-error is passed).

Usage:
    python scripts/production_checklist.py [--exit-on-error]
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Callable


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Checklist:
    results: list[CheckResult] = field(default_factory=list)

    def run(self, name: str, fn: Callable[[], tuple[bool, str]]) -> None:
        try:
            passed, detail = fn()
        except Exception as exc:
            passed, detail = False, str(exc)
        self.results.append(CheckResult(name, passed, detail))
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}{': ' + detail if detail else ''}")

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    def summary(self) -> None:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        print()
        print(f"Results: {passed}/{total} passed", end="")
        if failed:
            print(f"  ({failed} FAILED)", end="")
        print()


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

REQUIRED_VARS = [
    "ANTHROPIC_API_KEY",
    "DATABASE_URL",
    "LINKEDIN_CLIENT_ID",
    "LINKEDIN_CLIENT_SECRET",
    "LINKEDIN_ACCESS_TOKEN",
    "LINKEDIN_PROFILE_URN",
]

OPTIONAL_WARN_VARS = [
    "API_KEY",
    "SLACK_WEBHOOK_URL",
    "GOOGLE_SHEET_ID",
]


def check_required_env_vars() -> tuple[bool, str]:
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        return False, "Missing: " + ", ".join(missing)
    return True, ""


def check_placeholder_secrets() -> tuple[bool, str]:
    placeholders = [v for v in REQUIRED_VARS if os.environ.get(v) == "REPLACE_ME"]
    if placeholders:
        return False, "Still set to REPLACE_ME: " + ", ".join(placeholders)
    return True, ""


def check_optional_env_vars() -> tuple[bool, str]:
    missing = [v for v in OPTIONAL_WARN_VARS if not os.environ.get(v)]
    if missing:
        return True, f"Optional vars not set (non-blocking): {', '.join(missing)}"
    return True, ""


def check_database_url_format() -> tuple[bool, str]:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        return False, f"Expected postgresql:// scheme, got: {url[:30]}"
    return True, ""


def check_database_connectivity() -> tuple[bool, str]:
    try:
        import psycopg2  # type: ignore[import]
    except ImportError:
        return False, "psycopg2 not installed"

    url = os.environ.get("DATABASE_URL", "")
    try:
        conn = psycopg2.connect(url, connect_timeout=5)
        conn.close()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def check_anthropic_api_key_format() -> tuple[bool, str]:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or key == "test-key" or key == "REPLACE_ME":
        return False, "API key looks invalid or is a placeholder"
    if not key.startswith("sk-ant-"):
        return False, "Key doesn't match expected 'sk-ant-' prefix"
    return True, ""


def check_environment_value() -> tuple[bool, str]:
    env = os.environ.get("ENVIRONMENT", "development")
    if env != "production":
        return False, f"ENVIRONMENT={env!r} (expected 'production')"
    return True, ""


def check_log_level() -> tuple[bool, str]:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if level not in valid:
        return False, f"LOG_LEVEL={level!r} not in {valid}"
    if level == "DEBUG":
        return True, "LOG_LEVEL=DEBUG — consider INFO or WARNING in production"
    return True, ""


def check_google_credentials_file() -> tuple[bool, str]:
    approval_required = os.environ.get("APPROVAL_REQUIRED", "true").lower() == "true"
    if not approval_required:
        return True, "APPROVAL_REQUIRED=false — skipping"
    creds_file = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_FILE", "./credentials.json")
    if not os.path.isfile(creds_file):
        return False, f"File not found: {creds_file}"
    return True, ""


def check_storage_mode() -> tuple[bool, str]:
    mode = os.environ.get("STORAGE_MODE", "local")
    if mode == "local":
        return True, "STORAGE_MODE=local — ensure /data/content is mounted"
    if mode == "s3":
        missing = [v for v in ("AWS_S3_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
                   if not os.environ.get(v) or os.environ.get(v) == "REPLACE_ME"]
        if missing:
            return False, "S3 mode but missing: " + ", ".join(missing)
    return True, ""


def check_linkedin_profile_urn_format() -> tuple[bool, str]:
    urn = os.environ.get("LINKEDIN_PROFILE_URN", "")
    if not urn.startswith("urn:li:person:"):
        return False, f"Expected 'urn:li:person:...' format, got: {urn!r}"
    return True, ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Production pre-deploy checklist")
    parser.add_argument("--exit-on-error", action="store_true",
                        help="Exit with code 1 if any check fails")
    args = parser.parse_args()

    print("=" * 60)
    print("LinkedIn Auto-Publisher — Production Checklist")
    print("=" * 60)

    cl = Checklist()

    print("\n[Environment]")
    cl.run("ENVIRONMENT=production", check_environment_value)
    cl.run("Required env vars set", check_required_env_vars)
    cl.run("No placeholder secrets", check_placeholder_secrets)
    cl.run("Optional env vars", check_optional_env_vars)
    cl.run("LOG_LEVEL valid", check_log_level)

    print("\n[Database]")
    cl.run("DATABASE_URL format", check_database_url_format)
    cl.run("Database connectivity", check_database_connectivity)

    print("\n[LLM / API]")
    cl.run("Anthropic API key format", check_anthropic_api_key_format)

    print("\n[LinkedIn]")
    cl.run("LINKEDIN_PROFILE_URN format", check_linkedin_profile_urn_format)

    print("\n[Storage]")
    cl.run("Storage configuration", check_storage_mode)

    print("\n[Approval workflow]")
    cl.run("Google credentials file", check_google_credentials_file)

    cl.summary()

    if not cl.all_passed:
        failed = [r.name for r in cl.results if not r.passed]
        print(f"\nFailed checks: {', '.join(failed)}")
        if args.exit_on_error:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
