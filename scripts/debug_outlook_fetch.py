import asyncio
from src.core.graph_auth import GraphAuth
from src.integrations.azure.outlook_client import OutlookClient
from src.app.config import settings


async def main():
    auth = GraphAuth()
    mailbox = settings.EMAIL_USER or "testAI@tpgt-titan.com"
    folder_name = settings.FUCHS_FOLDER or "Inbox"
    client = OutlookClient(auth, mailbox=mailbox, folder_name=folder_name)

    messages = await client.fetch_last_messages(limit=3)

    for m in messages:
        print("=" * 60)
        print("SUBJECT:", m["subject"])
        print("FROM:", m["from"]["emailAddress"]["address"])
        print("BODY len:", len(m["body"]["content"]))

        attachments = client.parse_attachments(m.get("attachments"))
        print("ATTACHMENTS:", [a["name"] for a in attachments])


if __name__ == "__main__":
    asyncio.run(main())
