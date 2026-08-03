"""One-off probe for TV Royale / leaderboards API (dev only)."""
import asyncio
import json

from dotenv import load_dotenv

load_dotenv()

from bot.services.clash_api import ClashRoyaleClient


async def main() -> None:
    client = ClashRoyaleClient()
    try:
        boards = await client._request("/leaderboards")
        print("leaderboards type:", type(boards).__name__)
        if isinstance(boards, dict):
            print("leaderboards keys:", boards.keys())
            blist = boards.get("leaderboards") or boards.get("items") or []
        else:
            blist = boards
        print("leaderboards count:", len(blist))
        for b in blist[:25]:
            print(" ", b.get("id"), b.get("name"))

        events = await client._request("/events")
        print("events top keys:", events.keys() if isinstance(events, dict) else type(events))
        print(json.dumps(events, indent=2)[:8000])

        for lb_id in [1, 679855, 550072, 270785]:
            try:
                sample = await client._request(f"/leaderboards/{lb_id}?limit=2")
                print(f"leaderboard {lb_id} OK keys:", list(sample.keys()) if isinstance(sample, dict) else type(sample))
                if isinstance(sample, dict):
                    for p in (sample.get("items") or [])[:2]:
                        print(json.dumps(p, indent=2)[:2000])
            except Exception as e:
                print(f"leaderboard {lb_id} ERR", e)

        for tag in ["#2R2GCR2L"]:
            try:
                ev = await client._request(f"/events/{tag.replace('#', '%23')}")
                print("event detail keys", ev.keys() if isinstance(ev, dict) else type(ev))
                print(json.dumps(ev, indent=2)[:3000])
            except Exception as e:
                try:
                    from bot.services.clash_api import encode_tag
                    ev = await client._request(f"/events/{encode_tag(tag)}")
                    print(json.dumps(ev, indent=2)[:3000])
                except Exception as e2:
                    print("event detail ERR", e, e2)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
