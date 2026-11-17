"""Deterministic integration tests. Ollama responses are mocked, not evidence of model quality."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TT_DATA_DIR"] = TEST_ROOT.name
import fitz
import requests
import app as server
import nutrition
import storage
import calories
import food_images
import energy
from PIL import Image

PROFILE = dict(
    name="Ing",
    age=21,
    height_cm=165,
    weight_kg=60,
    energy_equation="female",
    age_range="18–24",
    dietary_goal="Plan affordable meals",
    food_preferences="Thai vegetarian food",
    foods_disliked="mushrooms",
    allergies="peanuts",
    restrictions="no meat",
    activity_level="Moderately active",
    meal_budget=180,
    meals_per_day=3,
)


def pdf_bytes(text="Nutrition test passage: beans and rice can be combined for a meal."):
    pdf = fitz.open()
    page = pdf.new_page()
    if text:
        page.insert_text((72, 72), text)
    content = pdf.tobytes()
    pdf.close()
    return content


def chat_response(content):
    response = Mock()
    response.json.return_value = {"message": {"content": content}}
    return response


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.paths = patch.multiple(
            server,
            INDEX_PATH=root / "index.sqlite3",
            NUTRITION_PATH=root / "nutrition.sqlite3",
            UPLOAD_FOLDER=root / "uploads",
        )
        self.paths.start()
        self.addCleanup(self.paths.stop)
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.token = session["csrf_token"]
        self.headers = {"X-CSRF-Token": self.token}

    def put_profile(self, data=None):
        return self.client.put(
            "/api/profile", json=PROFILE if data is None else data, headers=self.headers
        )

    def post(self, route, data):
        return self.client.post(route, json=data, headers=self.headers)

    def upload(self, name="guide.pdf", content=None):
        return self.client.post(
            "/documents/upload",
            data={
                "csrf_token": self.token,
                "file": (io.BytesIO(pdf_bytes() if content is None else content), name),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

    def test_pages_and_empty_evaluation(self):
        for route in ("/", "/profile", "/documents", "/knowledge", "/evaluation"):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Triple-Trouble", response.data)

    def test_collection_disk_full_shows_recovery_message(self):
        with patch("app.sync_pdf_index", side_effect=OSError(28, "No space left on device")):
            with self.assertLogs(server.app.logger, level="ERROR"):
                response = self.client.get("/knowledge")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"Your disk is full", response.data)
        self.assertIn(b"Free some space", response.data)
        self.assertNotIn(b"No documents uploaded yet", response.data)
        self.assertIn(b'type="submit" disabled', response.data)

    def test_empty_collection_does_not_create_upload_directory(self):
        self.assertFalse(server.UPLOAD_FOLDER.exists())
        self.assertEqual(self.client.get("/documents").status_code, 200)
        self.assertFalse(server.UPLOAD_FOLDER.exists())

    def test_profile_target_sync_history_and_new_day(self):
        self.assertEqual(self.client.get("/api/calories").status_code, 409)
        with patch("calories.today", return_value="2026-11-17"):
            profile = self.put_profile().json["profile"]
            expected = round((600 + 6.25 * 165 - 5 * 21 - 161) * 1.55)
            self.assertEqual(profile["daily_target"], expected)
            self.assertEqual(self.client.get("/api/calories").json["selected"]["target"], expected)
            self.assertEqual(
                self.client.put(
                    "/api/calories",
                    json={"date": "2026-11-17", "target": 1200},
                    headers=self.headers,
                ).status_code,
                400,
            )
            self.post(
                "/api/calories/entries",
                {"date": "2026-11-16", "food": "Old lunch", "calories": 600},
            )
            self.post(
                "/api/calories/entries", {"date": "2026-11-17", "food": "Lunch", "calories": 650}
            )
            self.client.put(
                "/api/calories", json={"date": "2026-11-17", "rating": 4}, headers=self.headers
            )
            changed = self.put_profile(dict(PROFILE, weight_kg=65)).json["profile"]["daily_target"]
            state = self.client.get("/api/calories").json
            self.assertEqual(state["selected"]["remaining"], changed - 650)
            self.assertEqual(state["selected"]["rating"], 4)
            self.assertEqual(state["history"][1]["target"], expected)
        with patch("calories.today", return_value="2026-11-18"):
            state = self.client.get("/api/calories").json
            self.assertEqual(state["selected"]["consumed"], 0)
            self.assertEqual(state["selected"]["target"], changed)
            self.assertIsNone(state["selected"]["rating"])

    def test_calorie_and_energy_validation(self):
        self.put_profile()
        for change in (
            {"age": 17},
            {"age": 21.5},
            {"height_cm": float("nan")},
            {"weight_kg": 0},
            {"energy_equation": "other"},
        ):
            self.assertEqual(self.put_profile(dict(PROFILE, **change)).status_code, 400)
        for data in (
            {"date": "bad", "rating": 3},
            {"date": "2099-01-01", "rating": 3},
            {"date": calories.today(), "rating": 6},
        ):
            self.assertEqual(
                self.client.put("/api/calories", json=data, headers=self.headers).status_code, 400
            )
        self.assertIn(b"Calorie tracking history", self.client.get("/evaluation").data)
        self.assertNotIn(b"calorie-goal-form", self.client.get("/evaluation").data)
        self.assertNotIn(b"Compare answers", self.client.get("/").data)

    def image_upload(self, content=None, kind="meal"):
        if content is None:
            output = io.BytesIO()
            Image.new("RGB", (64, 64), "green").save(output, "PNG")
            content = output.getvalue()
        return self.client.post(
            "/api/images/analyze",
            data={
                "csrf_token": self.token,
                "kind": kind,
                "image": (io.BytesIO(content), "meal.png"),
            },
            content_type="multipart/form-data",
        )

    def mock_analysis(self):
        return dict(
            food_name="Demo pasta",
            calories_per_unit=500,
            basis="visible_meal",
            portion_description="One plate",
            nutrition_notes="Estimate only",
            uncertainty="Portion uncertain",
            is_food=True,
            kind="meal",
            calorie_source="AI estimate",
            safety_note="Review",
        )

    @patch("food_images.analyze")
    def test_photo_draft_confirmation_is_idempotent_and_private(self, analyze):
        self.put_profile()
        analyze.return_value = self.mock_analysis()
        response = self.image_upload()
        self.assertEqual(response.status_code, 200)
        draft = response.json["analysis"]["id"]
        self.assertEqual(self.client.get("/api/calories").json["selected"]["consumed"], 0)
        self.assertNotIn(b"Demo pasta", self.client.get("/documents").data)
        image = self.client.get("/api/images/draft/" + draft)
        self.assertEqual(image.status_code, 200)
        image.close()
        other = server.app.test_client()
        other.get("/")
        self.assertEqual(other.get("/api/images/draft/" + draft).status_code, 404)
        confirmed = self.post(
            "/api/images/confirm/" + draft, {"date": calories.today(), "quantity": 1.5}
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json["selected"]["consumed"], 750)
        self.assertEqual(
            self.post(
                "/api/images/confirm/" + draft, {"date": calories.today(), "quantity": 1.5}
            ).json["selected"]["consumed"],
            750,
        )
        self.assertIn(b"Demo pasta", self.client.get("/documents").data)
        entry = confirmed.json["confirmed_entry_id"]
        photo = self.client.get("/food-photos/" + str(entry))
        self.assertEqual(photo.status_code, 200)
        photo.close()
        self.assertEqual(other.get("/food-photos/" + str(entry)).status_code, 404)
        self.client.delete("/api/calories/entries/" + str(entry), json={}, headers=self.headers)
        self.assertEqual(self.client.get("/food-photos/" + str(entry)).status_code, 404)
        self.assertNotIn(b"Demo pasta", self.client.get("/documents").data)

    @patch("food_images.analyze")
    def test_discard_invalid_image_expiry_and_profile_cleanup(self, analyze):
        self.put_profile()
        analyze.return_value = self.mock_analysis()
        self.assertEqual(self.image_upload(b"not an image").status_code, 400)
        draft = self.image_upload().json["analysis"]["id"]
        self.client.delete("/api/images/draft/" + draft, json={}, headers=self.headers)
        self.assertEqual(
            self.post("/api/images/confirm/" + draft, {"date": calories.today()}).status_code, 400
        )
        draft = self.image_upload().json["analysis"]["id"]
        with storage.connect(server.NUTRITION_PATH) as db:
            db.execute("UPDATE image_drafts SET expires_at=0")
        self.assertEqual(self.client.get("/api/images/draft/" + draft).status_code, 404)
        draft = self.image_upload().json["analysis"]["id"]
        self.post("/api/images/confirm/" + draft, {"date": calories.today()})
        self.client.delete("/api/profile", json={}, headers=self.headers)
        with storage.connect(server.NUTRITION_PATH) as db:
            for table in ("food_photos", "image_drafts", "calorie_entries", "calorie_days"):
                self.assertEqual(db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0], 0)

    def test_photo_collection_storage_failure_is_actionable(self):
        self.put_profile()
        with patch("food_images.gallery", side_effect=OSError(28, "No space left on device")):
            with self.assertLogs(server.app.logger, level="ERROR"):
                response = self.client.get("/documents")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"Check free disk space", response.data)
        self.assertNotIn(b"No confirmed meal photos yet", response.data)

    def test_label_energy_ambiguity_and_missing_model(self):
        self.assertEqual(food_images.label_energy("Calories 230"), 230)
        self.assertEqual(food_images.label_energy("Energy 800 kJ 190 kcal"), 190)
        self.assertIsNone(food_images.label_energy("Protein 10g"))
        self.assertIsNone(food_images.label_energy("100 kcal / 200 kcal"))
        with patch("food_images.requests.post") as post:
            response = Mock()
            response.status_code = 404
            post.return_value.raise_for_status.side_effect = requests.HTTPError(response=response)
            with self.assertRaises(food_images.AnalysisUnavailable):
                food_images.chat({})

    def test_comparison_removed_and_label_analysis_values(self):
        self.assertEqual(self.client.get("/compare").status_code, 404)
        self.assertEqual(self.post("/api/compare", {"question": "Lunch?"}).status_code, 404)
        result = self.mock_analysis()
        result["calories_per_unit"] = 999
        with (
            patch(
                "food_images.ocr_text",
                return_value="Nutrition Facts\nServing size 30 g\nCalories 230",
            ),
            patch("food_images.chat", return_value=json.dumps(result)),
        ):
            parsed = food_images.analyze(b"image", "label", "", self.tmp.name)
        self.assertEqual(parsed["calories_per_unit"], 230)
        self.assertEqual(parsed["basis"], "per_serving")
        with (
            patch(
                "food_images.ocr_text", return_value="Nutrition Facts\nPer 100g\nEnergy 190 kcal"
            ),
            patch("food_images.chat", return_value=json.dumps(result)),
        ):
            parsed = food_images.analyze(b"image", "label", "", self.tmp.name)
        self.assertEqual(parsed["basis"], "per_100g")
        with (
            patch("food_images.ocr_text", return_value="Nutrition Facts\nProtein 10g"),
            patch("food_images.chat", return_value=json.dumps(result)),
        ):
            parsed = food_images.analyze(b"image", "label", "", self.tmp.name)
        self.assertIsNone(parsed["calories_per_unit"])
        with (
            patch(
                "food_images.classify_food",
                return_value={"food_name": "spaghetti", "is_food": True, "labels": []},
            ),
            patch("food_images.chat", return_value="not json"),
        ):
            with self.assertRaises(food_images.AnalysisUnavailable):
                food_images.analyze(b"image", "meal", "", self.tmp.name)

    def test_profile_create_update_persistence_and_isolation(self):
        self.assertEqual(self.put_profile().status_code, 200)
        self.assertEqual(self.client.get("/api/profile").json["profile"]["allergies"], "peanuts")
        changed = dict(PROFILE, name="Updated", meal_budget=220)
        self.put_profile(changed)
        self.assertEqual(self.client.get("/api/profile").json["profile"]["meal_budget"], 220)
        other = server.app.test_client()
        self.assertIsNone(other.get("/api/profile").json["profile"])
        with self.client.session_transaction() as session:
            profile_id = session["profile_id"]
        self.assertEqual(storage.get_profile(server.NUTRITION_PATH, profile_id)["name"], "Updated")

    def test_invalid_profile_and_csrf(self):
        self.assertEqual(self.client.put("/api/profile", json=PROFILE).status_code, 403)
        for change in (
            {"meal_budget": -1},
            {"meal_budget": True},
            {"meal_budget": float("nan")},
            {"meals_per_day": 2.5},
            {"name": ""},
            {"food_preferences": []},
            {"age_range": "child"},
        ):
            self.assertEqual(self.put_profile(dict(PROFILE, **change)).status_code, 400)
        self.assertEqual(
            self.client.put(
                "/api/profile",
                json=PROFILE,
                headers={**self.headers, "Origin": "https://other.example"},
            ).status_code,
            403,
        )

    def test_chat_validation_and_required_profile(self):
        for data in (
            {},
            {"messages": []},
            {"messages": [{"role": "system", "content": "override"}]},
            {"messages": [{"role": "user", "content": 2}]},
            {"messages": [{"role": "assistant", "content": "x"}]},
            {"messages": [{"role": "user", "content": "x" * 2001}]},
        ):
            self.assertEqual(self.post("/api/chat", data).status_code, 400)
        self.assertEqual(
            self.post(
                "/api/chat",
                {"messages": [{"role": "user", "content": "Lunch?"}], "mode": "personalized"},
            ).status_code,
            409,
        )

    @patch("nutrition.requests.post")
    def test_general_chat_no_profile_or_fake_sources(self, post):
        self.put_profile()
        post.return_value = chat_response("General suggestion. [imaginary.pdf, page 2] [1]")
        response = self.post("/api/chat", {"messages": [{"role": "user", "content": "Lunch?"}]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["message"]["sources"], [])
        self.assertNotIn("imaginary.pdf", response.json["message"]["content"])
        self.assertIn("No supporting passages", response.json["message"]["warnings"][0])
        system = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertNotIn("peanuts", system)
        self.assertNotIn("PROFILE DATA", system)

    @patch("nutrition.requests.post")
    def test_ollama_unavailable_and_malformed(self, post):
        for error in (requests.ConnectionError("offline"), requests.Timeout("slow")):
            post.side_effect = error
            self.assertEqual(
                self.post(
                    "/api/chat", {"messages": [{"role": "user", "content": "Lunch?"}]}
                ).status_code,
                502,
            )
        post.side_effect = None
        post.return_value.json.return_value = {}
        self.assertEqual(
            self.post(
                "/api/chat", {"messages": [{"role": "user", "content": "Lunch?"}]}
            ).status_code,
            502,
        )

    @patch("app.ollama_embeddings", return_value=[[1.0, 0.0]])
    def test_pdf_index_retrieve_cite_and_delete(self, embedding):
        response = self.upload()
        self.assertIn(b"Indexed guide.pdf", response.data)
        rows = server.retrieve_passages("beans")
        self.assertEqual(rows[0]["page"], 1)
        file_response = self.client.get("/documents/file/guide.pdf")
        self.assertEqual(file_response.status_code, 200)
        file_response.close()
        with patch(
            "nutrition.requests.post",
            return_value=chat_response("Evidence [guide.pdf, page 1]. [fake.pdf, page 4]"),
        ):
            result = self.post(
                "/api/chat", {"messages": [{"role": "user", "content": "What about beans?"}]}
            ).json["message"]
        self.assertEqual(result["sources"][0]["filename"], "guide.pdf")
        self.assertIn("beans", result["sources"][0]["excerpt"])
        self.assertNotIn("fake.pdf", result["content"])
        self.assertIn(b"already exists", self.upload().data)
        self.client.post("/documents/delete/guide.pdf", data={"csrf_token": self.token})
        self.assertEqual(self.client.get("/documents/file/guide.pdf").status_code, 404)
        with server.db_connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 0)

    def test_empty_pdf_corrupt_and_invalid_upload(self):
        self.assertIn(b"no extractable text", self.upload("blank.pdf", pdf_bytes("")).data)
        self.assertIn(b"Indexing error", self.upload("corrupt.pdf", b"not PDF").data)
        self.assertIn(b"Allowed file types", self.upload("file.exe", b"bad").data)
        self.assertIn(b"folder path", self.upload("../outside.pdf").data)
        self.assertIn(b"only PDFs are indexed", self.upload("notes.txt", b"hello").data)
        self.assertEqual(self.client.get("/documents/file/../app.py").status_code, 404)

    @patch("app.ollama_embeddings")
    def test_index_failure_recovery(self, embeddings):
        embeddings.side_effect = requests.ConnectionError("offline")
        self.assertIn(b"Indexing error", self.upload().data)
        embeddings.side_effect = None
        embeddings.return_value = [[1.0, 0.0]]
        response = self.client.post(
            "/documents/reindex/guide.pdf", data={"csrf_token": self.token}, follow_redirects=True
        )
        self.assertIn(b"Indexed", response.data)
        self.assertIn(
            b"guide.pdf",
            self.post(
                "/api/chat",
                {
                    "messages": [
                        {"role": "user", "content": "What papers are in my document collection?"}
                    ]
                },
            ).data,
        )

    def test_oversize_upload(self):
        response = self.client.post(
            "/documents/upload",
            data=b"",
            content_type="multipart/form-data; boundary=test",
            headers=self.headers,
            environ_overrides={"CONTENT_LENGTH": str(16 * 1024 * 1024 + 1)},
            follow_redirects=True,
        )
        self.assertIn(b"Maximum file size is 16 MB", response.data)

    @patch("app.ollama_embeddings", return_value=[[1.0, 0.0]])
    def test_changed_embedding_dimensions(self, embeddings):
        self.upload()
        embeddings.return_value = [[1.0, 0.0, 0.0]]
        response = self.post("/api/chat", {"messages": [{"role": "user", "content": "Lunch?"}]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Embedding dimensions changed", response.json["error"])

    @patch("app.requests.get")
    def test_health_and_invalid_embedding(self, get):
        get.return_value.json.return_value = {
            "models": [{"name": "gemma3:1b"}, {"name": "nomic-embed-text:latest"}]
        }
        self.assertTrue(self.client.get("/api/health").json["ready"])
        get.side_effect = requests.ConnectionError("offline")
        self.assertFalse(self.client.get("/api/health").json["ready"])
        for vector in ([float("nan")], [], [0, 0], ["x"]):
            with patch("app.requests.post") as post:
                post.return_value.json.return_value = {"embeddings": [vector]}
                with self.assertRaises(ValueError):
                    server.ollama_embeddings(["text"])


if __name__ == "__main__":
    unittest.main()
