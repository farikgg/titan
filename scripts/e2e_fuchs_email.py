import asyncio
from src.core.graph_auth import GraphAuth
from src.integrations.azure.outlook_client import OutlookClient
from src.services.fuchs_parser import FuchsAIParser
from src.services.price_service import PriceService
from src.db.initialize import async_session
from src.app.config import settings


async def main():
    auth = GraphAuth()
    mailbox = settings.EMAIL_USER or "testAI@tpgt-titan.com"
    folder_name = settings.FUCHS_FOLDER or "Inbox"
    outlook = OutlookClient(auth, mailbox=mailbox, folder_name=folder_name)
    parser = FuchsAIParser()
    price_service = PriceService()

    messages = await outlook.fetch_last_messages(limit=1)
    msg = messages[0]

    attachments = outlook.parse_attachments(msg.get("attachments"))
    attachment_text = parser.extract_text_from_attachments(attachments)

    items = await parser.parse_to_objects(msg["body"]["content"], attachment_text)

    async with async_session() as session:
        for item in items:
            await price_service.update_or_create(session, item)
        await session.commit()

    print("E2E DONE, saved:", len(items))


if __name__ == "__main__":
    asyncio.run(main())
