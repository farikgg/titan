# tests/factories/email_factory.py

def fuchs_email_with_excel(message_id="msg-1"):
    return {
        "message_ids": message_id,
        "subject": "FUCHS price update",
        "body": "See attached price list",
        "attachments": [
            {
                "name": "prices.xlsx",
                "content": b"fake-excel-bytes"
            }
        ],
    }


def fuchs_email_no_excel(message_id="msg-2"):
    return {
        "message_ids": message_id,
        "subject": "FUCHS prices",
        "body": "Prices in body",
        "attachments": [],
    }
