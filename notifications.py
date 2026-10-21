"""SMTP delivery with a transactional outbox and bounded retries."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate
from inventory import quantity
from qr_labels import cabinet_url


def send_email(settings, alert):
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = alert["email"]
    message["Subject"] = f"Low stock: {alert['item_name']} · {alert['cabinet_name']}"
    message["Date"] = formatdate(localtime=False)
    # Stable ID helps mail servers recognize retries after an interrupted delivery.
    message["Message-ID"] = f"<lab-inventory-{alert['id']}@{settings.smtp_from.split('@')[-1]}>"
    link = cabinet_url(settings.base_url, alert["cabinet_id"]) if settings.base_url else "Open your lab inventory app."
    message.set_content(
        f"Hello {alert['recipient_name']},\n\n"
        f"{alert['item_name']} ({alert['detail'] or 'no description'}) is low in {alert['cabinet_name']}.\n"
        f"Location: {alert['location']}\n"
        f"Remaining when checked: {quantity(alert['current_quantity'])} {alert['unit']}\n"
        f"Low-stock threshold: {quantity(alert['current_threshold'])} {alert['unit']}\n"
        f"Low-stock event: {alert['created_at']}\n\n"
        f"Please arrange a refill.\n{link}\n\nLab Inventory\n"
    )
    context = ssl.create_default_context()
    connection = (smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15, context=context)
                  if settings.smtp_security == "ssl"
                  else smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15))
    with connection as smtp:
        if settings.smtp_security == "starttls":
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def dispatch_pending(store, settings, limit=5, sender=None):
    result = {"sent": 0, "failed": 0, "disabled": settings.demo or not settings.mail_ready}
    if result["disabled"]:
        return result
    for _ in range(limit):
        alert = store.claim_alert()
        if alert is None:
            break
        try:
            (sender or send_email)(settings, alert)
        except Exception as exc:
            # Keep credentials / provider response text out of the database and UI.
            store.finish_alert(alert["id"], alert["claim_token"], f"{type(exc).__name__}: delivery failed; check SMTP configuration or connectivity.")
            result["failed"] += 1
            break
        else:
            store.finish_alert(alert["id"], alert["claim_token"])
            result["sent"] += 1
    return result
