"""Run alongside Streamlit to retry queued mail even when no one is using the app."""
import argparse
import time
from config import load_settings
from inventory import Store
from notifications import dispatch_pending


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process the queue once and exit (for a scheduler).")
    args = parser.parse_args()
    settings = load_settings()
    if settings.demo or not settings.mail_ready:
        raise SystemExit("Email worker inactive: turn off demo mode and configure SMTP first.")
    store = Store(settings.db_path)
    if store.metadata("demo") == "1":
        raise SystemExit("Refusing to send mail for a sample database. Choose a new LAB_DB_PATH.")
    while True:
        result = dispatch_pending(store, settings, limit=50)
        print(f"Mail queue: {result['sent']} sent, {result['failed']} failed.", flush=True)
        if args.once:
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
