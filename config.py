"""Environment / Streamlit secrets configuration shared with the mail worker."""
import os
from dataclasses import dataclass
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parent


def load_settings():
    path = ROOT / ".streamlit" / "secrets.toml"
    secrets = tomllib.loads(path.read_text()) if path.exists() else {}
    def get(key, default=""):
        return str(os.environ.get(key, secrets.get(key, default))).strip()
    mode = get("LAB_DEMO", "true").lower() in ("true", "1", "yes")
    return Settings(
        db_path=get("LAB_DB_PATH", str(ROOT / "data" / ("demo.sqlite3" if mode else "inventory.sqlite3"))),
        demo=mode, admin_password=get("LAB_ADMIN_PASSWORD"), access_code=get("LAB_ACCESS_CODE"),
        base_url=get("LAB_PUBLIC_URL"), smtp_host=get("LAB_SMTP_HOST"),
        smtp_port=int(get("LAB_SMTP_PORT", "587")), smtp_username=get("LAB_SMTP_USERNAME"),
        smtp_password=get("LAB_SMTP_PASSWORD"), smtp_from=get("LAB_SMTP_FROM"),
        smtp_security=get("LAB_SMTP_SECURITY", "starttls").lower(),
    )


@dataclass(frozen=True)
class Settings:
    db_path: str
    demo: bool = True
    admin_password: str = ""
    access_code: str = ""
    base_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_security: str = "starttls"

    @property
    def mail_ready(self):
        return bool(self.smtp_host and self.smtp_from and self.smtp_security in ("starttls", "ssl")
                    and (not self.smtp_username or self.smtp_password))
