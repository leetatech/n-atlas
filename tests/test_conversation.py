import asyncio
import importlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src import conversation, leeta_service, session_manager
from src.intent_parser import extract_gas_order_intent


VENDORS = [
    {"vendor_id": "v1", "product_id": "p1", "business_name": "Closest Gas", "distance_km": 1},
    {"vendor_id": "v2", "product_id": "p2", "business_name": "Second Gas", "distance_km": 3},
]
LOCATION = {"address": "10 Main Street, Lagos", "lat": 6.5, "lng": 3.4}


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / "sessions.sqlite3"
        self.start_patch(patch.object(session_manager, "SESSION_DB_PATH", self.db))
        self.geocode = self.start_patch(patch.object(
            conversation, "geocode_address", AsyncMock(return_value=LOCATION)
        ))
        self.vendors = self.start_patch(patch.object(
            conversation, "get_nearby_vendors", AsyncMock(return_value=VENDORS)
        ))
        self.order = self.start_patch(patch.object(
            conversation, "create_guest_leeta_order", AsyncMock(return_value={"id": "order1"})
        ))
        self.send = self.start_patch(patch.object(
            conversation, "send_whatsapp_message", AsyncMock()
        ))
        self.count = 0

    def start_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    async def message(self, text, phone="whatsapp:+234111", sid=None):
        self.count += 1
        await conversation.handle_user_message(phone, sid or f"SM{self.count}", text)

    def state(self, phone="whatsapp:+234111"):
        return session_manager.get_session(phone)

    async def choose_vendor(self, opening="order 6kg gas"):
        await self.message(opening)
        await self.message(LOCATION["address"])
        await self.message("1")

    async def test_order_requires_address_and_vendor(self):
        await self.message("order 6kg gas")
        self.order.assert_not_awaited()
        self.assertEqual(self.state()["step"], "awaiting_address")
        await self.message(LOCATION["address"])
        self.geocode.assert_awaited_once_with(LOCATION["address"])
        self.vendors.assert_awaited_once_with(6.5, 3.4)
        self.order.assert_not_awaited()
        await self.message("1")
        self.order.assert_awaited_once_with(
            customer_phone="whatsapp:+234111", size_kg=6.0,
            transcription="order 6kg gas", product_id="p1", vendor_id="v1",
            address=LOCATION["address"], lat=6.5, lng=3.4,
        )
        self.assertEqual(self.state()["step"], "order_created")

    async def test_browsing_never_orders_without_intent(self):
        await self.choose_vendor("find gas vendors near me")
        self.order.assert_not_awaited()
        self.assertEqual(self.state()["step"], "awaiting_order")
        await self.message("thanks")
        self.order.assert_not_awaited()
        await self.message("order gas 3kg")
        self.order.assert_awaited_once()

    async def test_greeting_starts_address_collection(self):
        await self.message("hello")
        self.assertEqual(self.state()["step"], "awaiting_address")
        self.vendors.assert_not_awaited()
        self.order.assert_not_awaited()

    async def test_quantity_required_and_address_numbers_not_used(self):
        await self.choose_vendor("I want gas")
        self.assertEqual(self.state()["step"], "awaiting_size")
        self.order.assert_not_awaited()
        await self.message("0kg")
        self.order.assert_not_awaited()
        await self.message("6")
        self.assertEqual(self.order.await_args.kwargs["size_kg"], 6)

    async def test_invalid_vendor_cannot_order(self):
        await self.message("order gas 6kg")
        await self.message(LOCATION["address"])
        for choice in ("0", "99", "invented", "6kg"):
            await self.message(choice)
        self.assertEqual(self.state()["step"], "awaiting_vendor")
        self.order.assert_not_awaited()

    async def test_declining_pending_order_does_not_place_it(self):
        for decline_step in ("awaiting_vendor", "awaiting_size"):
            await self.message("cancel")
            await self.message("order gas")
            await self.message(LOCATION["address"])
            if decline_step == "awaiting_size":
                await self.message("1")
            await self.message("don't order gas 6kg")
            if decline_step == "awaiting_vendor":
                await self.message("1")
            self.order.assert_not_awaited()
            self.assertEqual(self.state()["step"], "awaiting_order")

    async def test_select_by_exact_name_and_id(self):
        for choice in ("second gas", "v2"):
            await self.message("cancel")
            await self.message("order gas 6kg")
            await self.message(LOCATION["address"])
            await self.message(choice)
            self.assertEqual(self.order.await_args.kwargs["vendor_id"], "v2")

    async def test_changed_address_clears_vendor(self):
        await self.choose_vendor("find gas vendors")
        await self.message("address: 11 New Road, Lagos")
        self.geocode.assert_awaited_with("11 New Road, Lagos")
        self.assertIsNone(self.state()["vendor"])
        self.assertEqual(self.state()["step"], "awaiting_vendor")
        self.order.assert_not_awaited()

    async def test_change_vendor_refreshes_list(self):
        await self.choose_vendor("find gas vendors")
        await self.message("change vendor")
        self.assertEqual(self.vendors.await_count, 2)
        self.assertIsNone(self.state()["vendor"])

    async def test_no_vendors_requests_another_address(self):
        self.vendors.return_value = []
        await self.message("order gas 6kg")
        await self.message(LOCATION["address"])
        self.assertEqual(self.state()["step"], "awaiting_address")
        self.order.assert_not_awaited()

    async def test_geocoding_failure_notifies_and_retains_step(self):
        self.geocode.side_effect = ValueError("Address is ambiguous")
        await self.message("order gas")
        with self.assertLogs(conversation.logger, level="ERROR"):
            await self.message("Lagos")
        self.assertEqual(self.state()["step"], "awaiting_address")
        self.assertIn("ambiguous", self.send.await_args.args[1])
        self.vendors.assert_not_awaited()

    async def test_vendor_failure_can_retry(self):
        self.vendors.side_effect = httpx.ConnectError("unavailable")
        await self.message("order gas")
        with self.assertLogs(conversation.logger, level="ERROR"):
            await self.message(LOCATION["address"])
        self.assertEqual(self.state()["step"], "finding_vendors")
        self.vendors.side_effect = None
        await self.message("retry")
        self.assertEqual(self.state()["step"], "awaiting_vendor")

    async def test_duplicate_and_concurrent_webhooks_only_order_once(self):
        await self.message("order 6kg gas")
        await self.message(LOCATION["address"])
        await asyncio.gather(
            self.message("1", sid="selection"),
            self.message("1", sid="selection"),
        )
        self.order.assert_awaited_once()
        self.assertEqual(self.state()["step"], "order_created")

    async def test_unverified_order_cannot_retry(self):
        self.order.side_effect = httpx.ReadTimeout("timeout")
        with self.assertLogs(conversation.logger, level="ERROR"):
            await self.choose_vendor()
        self.assertEqual(self.state()["step"], "order_unknown")
        for text in ("1", "order 6kg gas", "cancel", "change address"):
            await self.message(text)
        self.order.assert_awaited_once()
        self.assertEqual(self.state()["step"], "order_unknown")

    async def test_state_and_history_persist_with_user_isolation(self):
        await self.message("hello")
        await self.message("hello", phone="whatsapp:+234222")
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 2)
        history = session_manager.get_interactions("whatsapp:+234111")
        self.assertEqual([row["direction"] for row in history], ["inbound", "outbound", "state"])
        self.assertEqual(history[-1]["step"], "awaiting_address")
        await self.message("cancel")
        self.assertEqual(self.state()["step"], "idle")
        self.assertGreater(len(session_manager.get_interactions("whatsapp:+234111")), 3)
        self.assertEqual(self.state("whatsapp:+234222")["step"], "awaiting_address")

    async def test_new_order_requires_fresh_address_and_vendor(self):
        await self.choose_vendor()
        await self.message("order 3kg gas")
        self.order.assert_awaited_once()
        self.assertEqual(self.state()["step"], "awaiting_address")
        self.assertNotIn("vendor", self.state())

    async def test_failed_reply_does_not_change_successful_order_status(self):
        await self.message("order 6kg gas")
        await self.message(LOCATION["address"])
        self.send.side_effect = httpx.ConnectError("Twilio unavailable")
        with self.assertLogs(conversation.logger, level="ERROR"):
            with self.assertRaises(conversation.ReplyDeliveryError):
                await self.message("1")
        self.assertEqual(self.state()["step"], "order_created")
        self.order.assert_awaited_once()
        self.assertEqual(self.send.await_count, 3)
        self.assertIn(
            "delivery_failed",
            [item["direction"] for item in session_manager.get_interactions("whatsapp:+234111")],
        )

    async def test_voice_and_text_worker_share_flow(self):
        asr = MagicMock()
        asr.asr_service.transcribe_and_detect_language.return_value = {
            "transcription": "order 6kg gas", "language": "yo", "language_name": "Yoruba",
        }
        with patch.dict("sys.modules", {"src.asr_engine": asr}):
            main = importlib.import_module("src.main")
        with patch.object(main, "handle_user_message", AsyncMock()) as handler:
            await main.process_incoming_message_background(
                "phone", "text_sid", False, "", text_content="hello"
            )
            handler.assert_awaited_with("phone", "text_sid", "hello", "en")
            with patch.object(main, "_download_twilio_audio", AsyncMock(return_value="unused.ogg")):
                await main.process_incoming_message_background(
                    "phone", "voice_sid", True, "", media_url="https://example.invalid/audio"
                )
            handler.assert_awaited_with("phone", "voice_sid", "order 6kg gas", "yo")

    def test_webhook_routes_text_and_requires_sender_and_message_id(self):
        from fastapi.testclient import TestClient

        with patch.dict("sys.modules", {"src.asr_engine": MagicMock()}):
            main = importlib.import_module("src.main")
        with patch.object(main, "handle_user_message", AsyncMock()) as handler:
            with TestClient(main.app) as client:
                response = client.post("/webhook/whatsapp", data={
                    "From": "whatsapp:+234111", "MessageSid": "SMwebhook",
                    "Body": "order gas 6kg", "NumMedia": "0",
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn("application/xml", response.headers["content-type"])
                handler.assert_awaited_once_with(
                    "whatsapp:+234111", "SMwebhook", "order gas 6kg", "en",
                )
                self.assertEqual(client.post("/webhook/whatsapp", data={"Body": "hi"}).status_code, 400)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def mock_client(self, data, method="get", status=200):
        client = AsyncMock()
        response = httpx.Response(
            status, json=data, request=httpx.Request(method.upper(), "https://example.invalid")
        )
        getattr(client, method).return_value = response
        manager = AsyncMock()
        manager.__aenter__.return_value = client
        patcher = patch.object(leeta_service.httpx, "AsyncClient", return_value=manager)
        patcher.start()
        self.addCleanup(patcher.stop)
        return client

    async def test_geocoding_returns_real_coordinates(self):
        client = self.mock_client({
            "status": "OK", "results": [{
                "types": ["street_address"],
                "geometry": {"location": {"lat": 6.5, "lng": 3.4}},
            }],
        })
        with patch.object(leeta_service, "GOOGLE_MAPS_API_KEY", "test-key"):
            self.assertEqual(await leeta_service.geocode_address(LOCATION["address"]), LOCATION)
        self.assertEqual(client.get.await_args.kwargs["params"]["address"], LOCATION["address"])

    async def test_reject_unresolved_ambiguous_or_broad_addresses(self):
        for data in (
            {"status": "ZERO_RESULTS"},
            {"status": "REQUEST_DENIED"},
            {"status": "OK", "results": []},
            {"status": "OK", "results": [{"partial_match": True}]},
            {"status": "OK", "results": [{}, {}]},
            {"status": "OK", "results": [{"types": ["locality"]}]},
            {"status": "OK", "results": [{"types": ["street_address"], "geometry": {}}]},
        ):
            with self.subTest(data=data):
                self.mock_client(data)
                with patch.object(leeta_service, "GOOGLE_MAPS_API_KEY", "test-key"):
                    with self.assertRaises(ValueError):
                        await leeta_service.geocode_address("address")

    async def test_missing_maps_key_fails_explicitly(self):
        with patch.object(leeta_service, "GOOGLE_MAPS_API_KEY", ""):
            with self.assertRaisesRegex(ValueError, "not configured"):
                await leeta_service.geocode_address("address")

    async def test_vendor_array_sorted_and_requested_at_geocoded_location(self):
        client = self.mock_client(list(reversed(VENDORS)))
        self.assertEqual(await leeta_service.get_nearby_vendors(6.5, 3.4), VENDORS)
        self.assertEqual(client.get.await_args.kwargs["params"], {
            "lat": 6.5, "lng": 3.4, "radius_km": 10,
        })

    async def test_vendor_errors_do_not_look_like_empty_results(self):
        for data in ({}, [{}], [{**VENDORS[0], "distance_km": -1}]):
            self.mock_client(data)
            with self.assertRaises(ValueError):
                await leeta_service.get_nearby_vendors(6.5, 3.4)
        self.mock_client({"error": "unavailable"}, status=500)
        with self.assertRaises(httpx.HTTPStatusError):
            await leeta_service.get_nearby_vendors(6.5, 3.4)

    async def test_order_payload_and_required_values(self):
        client = self.mock_client({"id": "order1"}, method="post", status=201)
        kwargs = dict(
            customer_phone="whatsapp:+234111", size_kg=6, transcription="order gas",
            product_id="p1", vendor_id="v1", address=LOCATION["address"], lat=6.5, lng=3.4,
        )
        await leeta_service.create_guest_leeta_order(**kwargs)
        payload = client.post.await_args.kwargs["json"]
        for field in ("address", "lat", "lng", "vendor_id", "product_id"):
            self.assertEqual(payload[field], kwargs[field])
        for field, value in (
            ("address", ""), ("vendor_id", ""), ("product_id", ""),
            ("size_kg", 0), ("lat", 91), ("lng", float("nan")),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    await leeta_service.create_guest_leeta_order(**{**kwargs, field: value})
        self.assertEqual(client.post.await_count, 1)

    async def test_order_service_error_raises(self):
        self.mock_client({"status": "error"}, method="post")
        with self.assertRaises(ValueError):
            await leeta_service.create_guest_leeta_order(
                "phone", 6, "order", "p1", "v1", LOCATION["address"], 6.5, 3.4,
            )

    async def test_whatsapp_failure_is_not_silent(self):
        self.mock_client({}, method="post", status=500)
        with patch.object(leeta_service, "TWILIO_ACCOUNT_SID", "test-sid"), \
                patch.object(leeta_service, "TWILIO_AUTH_TOKEN", "test-token"):
            with self.assertRaises(httpx.HTTPStatusError):
                await leeta_service.send_whatsapp_message("phone", "reply")


class IntentTests(unittest.TestCase):
    def test_order_and_discovery_are_distinct(self):
        for text in ("find gas vendors near me", "where can I find gas", "hello", "buy food",
                     "don't order gas", "do not buy gas", "not gas", "gas is expensive",
                     "I want gas vendors near me", "gas"):
            with self.subTest(text=text):
                self.assertFalse(extract_gas_order_intent(text)["is_gas_order"])
        self.assertTrue(extract_gas_order_intent("I want to buy gas 6kg")["is_gas_order"])

    def test_size_requires_units_and_is_positive(self):
        for text in ("10 Main Street", "gas", "0kg", "-1kg"):
            with self.subTest(text=text):
                self.assertIsNone(extract_gas_order_intent(text)["size_kg"])
        self.assertEqual(extract_gas_order_intent("order 3kg gas")["size_kg"], 3)
        self.assertEqual(extract_gas_order_intent("order 12kg gas")["size_kg"], 12.5)
