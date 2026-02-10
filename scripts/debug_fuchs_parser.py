import asyncio

from src.integrations.azure.outlook_client import OutlookClient
from src.core.graph_auth import GraphAuth
from src.services.fuchs_parser import FuchsAIParser
from src.services.excel_parser import FuchsExcelParser


async def main():
    auth = GraphAuth()
    outlook = OutlookClient(auth)

    ai_parser = FuchsAIParser()
    excel_parser = FuchsExcelParser()

    messages = await outlook.fetch_last_messages(limit=2)

    for msg in messages:
        print("=" * 80)
        print("SUBJECT:", msg["subject"])

        attachments = outlook.parse_attachments(msg.get("attachments", []))
        items = []

        # 1. Excel FIRST
        for att in attachments:
            if att["name"].lower().endswith((".xls", ".xlsx")):
                items = excel_parser.parse(att["content"])
                if items:
                    print("EXCEL PARSED:", len(items))
                    break

        # 2. AI fallback
        if not items:
            attachment_text = ai_parser.extract_text_from_attachments(attachments)
            items = await ai_parser.parse_to_objects(
                msg["body"]["content"],
                attachment_text,
            )
            print("AI PARSED:", len(items))

        for i in items:
            print(i.model_dump())


if __name__ == "__main__":
    asyncio.run(main())
