import httpx

from app.catalog import Catalog
from app.main import create_app


def test_catalog_codes_are_unique_three_digit_and_complete():
    catalog = Catalog()
    codes = [item.code for item in catalog.items]
    assert codes[0] == "001" and len(codes) == len(set(codes)) >= 10
    for item in catalog.items:
        assert len(item.recycling.steps) == 3 and len(item.upcycling.steps) == 3


def test_catalog_content_avoids_unsafe_instructions():
    text = Catalog().items.__repr__().lower()
    for banned in ("burn the", "melt the", "heat gun", "blowtorch"):
        assert banned not in text


def test_code_normalisation_and_search():
    catalog = Catalog()
    assert catalog.get("001").name == "Water bottle"
    assert catalog.get("1").code == "001"
    assert catalog.get("#8").name == "Plastic carrier bag"
    assert catalog.get("999") is None and catalog.get("abc") is None
    assert [i.code for i in catalog.search("yogurt")] == ["005"]
    assert [i.code for i in catalog.search("styrofoam")] == ["011"]


async def test_item_endpoints(settings):
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        listing = (await client.get("/v1/items")).json()
        assert listing["items"][0] == {
            "code": "001",
            "name": "Water bottle",
            "aliases": ["plastic bottle", "pet bottle", "mineral water bottle"],
            "resin": {"number": 1, "type": "PET"},
        }
        assert [i["code"] for i in (await client.get("/v1/items", params={"q": "milk"})).json()["items"]] == ["003"]

        item = (await client.get("/v1/items/001")).json()
        assert item["name"] == "Water bottle"
        assert len(item["recycling"]["steps"]) == 3 and item["upcycling"]["title"]
        assert "photo cannot confirm" in item["safety_notice"]

        missing = await client.get("/v1/items/777")
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "item_not_found"
