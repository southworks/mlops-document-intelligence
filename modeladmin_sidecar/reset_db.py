"""CLI escape hatch to reset ModelAdmin DB tables directly (bypasses HTTP layer).

For normal demo resets prefer POST /admin/reset-demo, which drops/recreates tables
and re-seeds bootstrap data in a single HTTP call.
Use this only when the container is unreachable or the HTTP endpoint is unavailable.
"""

from modeladmin_sidecar.database.reset import reset_db


def main() -> None:
    reset_db()
    print("ModelAdmin DB reset complete.")


if __name__ == "__main__":
    main()
