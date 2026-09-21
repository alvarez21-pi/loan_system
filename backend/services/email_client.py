import os

import requests


def send_email(email_type, to, data):
    try:
        response = requests.post(
            os.getenv("EMAIL_SERVICE_URL", "http://email-service:80/index.php"),
            headers={"X-Internal-Secret": os.getenv("EMAIL_SERVICE_SECRET")},
            json={"type": email_type, "to": to, "data": data},
            timeout=10,
        )
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"error": str(exc)}
