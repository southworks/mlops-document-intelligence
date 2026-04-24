"""CLI entrypoint to reset ModelAdmin service database tables."""

from modeladmin_service.database.reset import reset_db


def main() -> None:
    reset_db()
    print("ModelAdmin DB reset complete.")


if __name__ == "__main__":
    main()
