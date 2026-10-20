#!/usr/bin/env python3

import json
import logging
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

PLAYBOOK = Path(
    "/home/karthi/devops-projects/self-healing-infrastructure/ansible/recover-nginx.yml"
)


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/alert":
            self.send_error(404, "Not found")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))

            if length <= 0 or length > 1_000_000:
                self.send_error(400, "Invalid request size")
                return

            payload = json.loads(self.rfile.read(length))
            alerts = payload.get("alerts", [])

            recover = any(
                alert.get("labels", {}).get("alertname") == "NginxDown"
                and alert.get("status") == "firing"
                for alert in alerts
            )

            if not recover:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"No NginxDown firing alert; no action taken.")
                return

            logging.warning("NginxDown alert received; running recovery playbook")

            result = subprocess.run(
                [
                    "/usr/bin/ansible-playbook",
                    "-i",
                    "localhost,",
                    "-c",
                    "local",
                    str(PLAYBOOK),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

            if result.returncode != 0:
                logging.error("Recovery failed: %s", result.stderr[-2000:])
                self.send_error(500, "Recovery playbook failed")
                return

            logging.info("Recovery playbook completed successfully")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Recovery playbook completed successfully.")

        except (ValueError, json.JSONDecodeError):
            self.send_error(400, "Invalid JSON")
        except subprocess.TimeoutExpired:
            logging.error("Recovery playbook timed out")
            self.send_error(504, "Recovery timed out")
        except Exception:
            logging.exception("Webhook processing failed")
            self.send_error(500, "Internal error")

    def log_message(self, format_string, *args):
        logging.info("%s - %s", self.address_string(), format_string % args)


if __name__ == "__main__":
    if not PLAYBOOK.is_file():
        raise SystemExit(f"Playbook not found: {PLAYBOOK}")

    server = HTTPServer(("172.18.0.1", 5001), WebhookHandler)
    logging.info("Recovery webhook listening on 172.18.0.1:5001")
    server.serve_forever()
