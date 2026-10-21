"""Phone links and printable QR labels, generated entirely on the server."""
from html import escape
from io import BytesIO
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import base64
import ipaddress
import qrcode


def validate_url(base):
    base = base.strip()
    if len(base.encode("utf-8")) > 1500 or any(ord(c) < 33 for c in base):
        raise ValueError("Use an app address under 1,500 bytes with no spaces or control characters.")
    parsed = urlsplit(base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Enter a full http:// or https:// address without credentials or a fragment.")
    host = parsed.hostname.lower()
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Enter a valid server port between 1 and 65535.")
    if host in ("localhost", "0.0.0.0", "::") or host.endswith(".localhost"):
        raise ValueError("Use the server's Wi-Fi IP address or hosted URL so phones can connect.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (address.is_loopback or address.is_unspecified):
        raise ValueError("A loopback or unspecified address will not work from a phone. Use the server's Wi-Fi address.")
    return base.rstrip("/")


def cabinet_url(base, cabinet_id=None):
    parsed = urlsplit(validate_url(base))
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k != "cabinet"]
    if cabinet_id:
        query.append(("cabinet", cabinet_id))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", urlencode(query), ""))


def qr_png(url):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=9, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    stream = BytesIO()
    qr.make_image(fill_color="#132e29", back_color="white").save(stream, format="PNG")
    return stream.getvalue()


def printable_labels(base, cabinets):
    cards = []
    for cabinet in [{"id": None, "name": "Lab inventory", "location": "Choose a cabinet after scanning"}, *cabinets]:
        url = cabinet_url(base, cabinet["id"])
        image = base64.b64encode(qr_png(url)).decode()
        cards.append(f'<article><p class="brand">LAB INVENTORY</p><h1>{escape(cabinet["name"])}</h1>'
                     f'<p>{escape(cabinet["location"])}</p><img alt="QR code" src="data:image/png;base64,{image}">'
                     f'<h2>Scan. Select. Update.</h2><p class="url">{escape(url)}</p></article>')
    return ('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lab inventory · QR labels</title><style>
body{font-family:Arial,sans-serif;color:#183a30;background:#f5f7f3;margin:24px}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px}
article{background:white;text-align:center;border:1px solid #ccc;border-radius:12px;padding:28px;break-inside:avoid}
.brand{letter-spacing:3px;font-size:11px}h1{font-size:25px}h2{font-size:18px}img{width:230px;max-width:100%}
.url{font-size:11px;overflow-wrap:anywhere}button{padding:12px 20px;margin-bottom:24px;cursor:pointer}
@media print{body{background:white;margin:0}button{display:none}main{grid-template-columns:1fr 1fr;gap:12mm}article{border-radius:0;padding:8mm}img{width:48mm}}
</style><button onclick="window.print()">Print labels</button><main>''' + "".join(cards) + "</main></html>").encode()
