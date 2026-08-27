from docx import Document

from app.modules.exports.renderer import render_docx


def test_renderer_uses_only_snapshot_content() -> None:
    document = Document(__import__("io").BytesIO(render_docx({
        "title": "Frozen itinerary",
        "start_date": "2026-08-07",
        "end_date": "2026-08-08",
        "days": [{"day_date": "2026-08-07", "events": [{"notes": "Museum", "starts_at": "09:00", "poi_snapshot": {"name": "City Museum"}}]}],
    })))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Frozen itinerary" in text
    assert "Museum" in text
    assert "City Museum" in text
