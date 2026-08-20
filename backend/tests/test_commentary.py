"""Management commentary: locating a document, reading it, and refusing to measure it.

Offline throughout. The markup fixture is a real company page's document sections, and the PDF
is generated in-process, so the extraction path is exercised for real rather than mocked into
always working.

The load-bearing tests are the last class. A transcript is the strongest temptation in the
platform to break "research produces context, never evidence" — it is full of confident
numbers stated by people with authority. Those tests are what keep one out of a verdict.
"""

from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from app.tools.commentary.providers import (
    Document,
    DocumentReader,
    ScreenerDocumentLocator,
    parse_documents,
    split_sections,
)
from app.tools.commentary.tool import TOOL, handle
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext

FIXTURE = Path(__file__).parent / "fixtures" / "screener" / "tcs_documents.html"


@pytest.fixture
def markup() -> str:
    return FIXTURE.read_text("utf-8")


def _pdf_bytes(lines: list[str]) -> bytes:
    """A minimal, valid single-page PDF containing the given lines.

    Built by hand rather than pulled from a fixture file so the extraction path is tested
    against a real PDF that a real parser must decompress and read.
    """
    text_ops = "BT /F1 12 Tf 40 750 Td 14 TL\n"
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        text_ops += f"({escaped}) Tj T*\n"
    text_ops += "ET"
    stream = zlib.compress(text_ops.encode("latin-1"))

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream)
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(out)


class TestLocatingDocuments:
    def test_transcripts_are_found_in_real_markup(self, markup: str) -> None:
        documents = parse_documents("TCS", markup)

        assert any(d.kind == "transcript" for d in documents)

    def test_documents_carry_their_period(self, markup: str) -> None:
        transcripts = [d for d in parse_documents("TCS", markup) if d.kind == "transcript"]

        assert transcripts[0].period is not None
        assert transcripts[0].period_end is not None

    def test_newest_first(self, markup: str) -> None:
        dated = [d for d in parse_documents("TCS", markup) if d.period_end]

        assert dated == sorted(dated, key=lambda d: d.period_end, reverse=True)

    def test_slide_decks_and_recordings_are_not_commentary(self, markup: str) -> None:
        """`PPT` and `REC` sit beside `Transcript` in the same row. Only prose is commentary."""
        transcripts = [d for d in parse_documents("TCS", markup) if d.kind == "transcript"]

        assert all("presentations" not in d.url.lower() for d in transcripts)

    def test_exchange_hosted_documents_are_recognised(self, markup: str) -> None:
        documents = parse_documents("TCS", markup)

        assert any(d.is_exchange_hosted for d in documents)

    def test_unparseable_markup_is_empty_not_an_error(self) -> None:
        assert parse_documents("TCS", "<html><body>nothing here</body></html>") == []

    def test_a_failing_lookup_returns_nothing(self) -> None:
        def boom(url: str):
            raise RuntimeError("blocked")

        assert ScreenerDocumentLocator(fetcher=boom).locate("TCS") == []

    def test_an_unknown_company_is_empty(self) -> None:
        assert ScreenerDocumentLocator(fetcher=lambda url: None).locate("NOPE") == []


class TestReadingDocuments:
    def test_a_real_pdf_is_extracted(self, tmp_path) -> None:
        pdf = _pdf_bytes(["Management commentary follows.", "Demand remains strong."])
        reader = DocumentReader(tmp_path / "docs", downloader=lambda url: pdf)

        text = reader.text("https://example.test/a.pdf")

        assert "Management commentary" in text

    def test_a_document_is_downloaded_once(self, tmp_path) -> None:
        pdf = _pdf_bytes(["Only once."])
        calls: list[str] = []

        def counted(url: str) -> bytes:
            calls.append(url)
            return pdf

        reader = DocumentReader(tmp_path / "docs", downloader=counted)
        reader.text("https://example.test/a.pdf")
        reader.text("https://example.test/a.pdf")

        assert len(calls) == 1

    def test_a_failed_download_is_none(self, tmp_path) -> None:
        def boom(url: str) -> bytes:
            raise RuntimeError("404")

        assert DocumentReader(tmp_path / "docs", downloader=boom).text("u") is None

    def test_an_unreadable_document_yields_no_partial_text(self, tmp_path) -> None:
        """Half a transcript read as though it were whole is worse than none."""
        reader = DocumentReader(
            tmp_path / "docs", downloader=lambda url: b"not a pdf at all"
        )

        assert reader.text("https://example.test/broken.pdf") is None

    def test_an_empty_document_is_none(self, tmp_path) -> None:
        reader = DocumentReader(
            tmp_path / "docs", downloader=lambda url: b"x", extractor=lambda b: "   "
        )

        assert reader.text("u") is None


class TestSections:
    def test_sections_reconstruct_the_document_order(self) -> None:
        text = "\n\n".join(f"Paragraph {i} " + "x" * 200 for i in range(10))

        sections = split_sections(text, section_chars=500)

        assert len(sections) > 1
        for index in range(10):
            assert f"Paragraph {index} " in "\n\n".join(sections)

    def test_sections_respect_the_bound(self) -> None:
        text = "\n\n".join("y" * 300 for _ in range(20))

        assert all(len(s) <= 700 for s in split_sections(text, section_chars=700))

    def test_an_oversized_paragraph_is_split_rather_than_dropped(self) -> None:
        sections = split_sections("z" * 5000, section_chars=1000)

        assert len(sections) == 5
        assert sum(len(s) for s in sections) == 5000

    def test_paragraph_boundaries_are_preferred(self) -> None:
        sections = split_sections("First para.\n\nSecond para.", section_chars=1000)

        assert sections == ["First para.\n\nSecond para."]

    def test_empty_text_has_no_sections(self) -> None:
        assert split_sections("", 1000) == []


class TestTheTool:
    def _context(self, documents: list[Document], sections: list[str]) -> ToolContext:
        class Locator:
            def locate(self, symbol: str) -> list[Document]:
                return documents

        class Reader:
            def sections(self, url: str) -> list[str]:
                return sections

        return ToolContext(fetchers={"document_locator": Locator(), "document_reader": Reader()})

    def _doc(self, url: str = "https://www.bseindia.com/x.pdf") -> Document:
        return Document(symbol="TCS", kind="transcript", url=url, period="Jul 2026")

    def test_sections_are_returned_with_their_provenance(self) -> None:
        context = self._context([self._doc()], ["alpha", "beta", "gamma"])

        result = handle({"symbol": "TCS"}, context)

        assert result["document_available"] is True
        assert result["items"][0]["source_ref"].endswith("#section=0")
        assert result["items"][0]["period"] == "Jul 2026"
        assert result["items"][0]["section_count"] == 3

    def test_a_specific_section_is_retrievable_alone(self) -> None:
        context = self._context([self._doc()], ["alpha", "beta", "gamma"])

        result = handle({"symbol": "TCS", "section": 2}, context)

        assert len(result["items"]) == 1
        assert result["items"][0]["text"] == "gamma"
        assert result["items"][0]["section_index"] == 2

    def test_a_section_past_the_end_is_empty_not_an_error(self) -> None:
        context = self._context([self._doc()], ["alpha"])

        assert handle({"symbol": "TCS", "section": 99}, context)["items"] == []

    def test_no_document_is_an_ordinary_empty_result(self) -> None:
        result = handle({"symbol": "TCS"}, self._context([], []))

        assert result["document_available"] is False
        assert "no transcript" in result["reason"]
        assert result["items"] == []

    def test_an_unreadable_document_reports_its_url(self) -> None:
        context = self._context([self._doc()], [])

        result = handle({"symbol": "TCS"}, context)

        assert result["document_available"] is False
        assert result["document_url"] in result["reason"]
        assert result["items"] == []

    def test_the_serving_provider_is_recorded(self) -> None:
        exchange = handle({"symbol": "TCS"}, self._context([self._doc()], ["a"]))
        elsewhere = handle(
            {"symbol": "TCS"},
            self._context([self._doc("https://company.example/x.pdf")], ["a"]),
        )

        assert exchange["provider"] == "exchange"
        assert elsewhere["provider"] == "aggregator"

    def test_output_satisfies_the_declared_schema(self) -> None:
        registry = ToolRegistry.discover()
        context = self._context([self._doc()], ["alpha", "beta"])

        result = registry.invoke("commentary", {"symbol": "TCS"}, context)

        assert result.ok, result.error
        assert len(result.items) == 2

    def test_the_tool_is_registered(self) -> None:
        assert ToolRegistry.discover().get("commentary") is not None


class TestCommentaryIsNeverAMeasurement:
    """`agent-graph`: research produces context, never evidence. This is where that is hardest."""

    def test_every_item_declares_it_was_not_measured_here(self) -> None:
        context = TestTheTool()._context(
            [Document(symbol="TCS", kind="transcript", url="https://www.bseindia.com/x.pdf")],
            ["Revenue will grow 25% next year, said the CEO."],
        )

        result = handle({"symbol": "TCS"}, context)

        assert result["items"][0]["measured_by_platform"] is False

    def test_the_schema_requires_a_followable_source(self) -> None:
        assert "source_ref" in TOOL.output_schema["properties"]["items"]["items"]["required"]

    def test_no_strategy_reads_commentary(self) -> None:
        """A number in a transcript has a speaker and an interest, not a threshold."""
        from tests.conftest import source_of

        strategies = source_of("strategies")
        assert "commentary" not in strategies
        assert "transcript" not in strategies

    def test_the_tool_makes_no_judgement(self) -> None:
        """No sentiment, no score, no rating — the same rule `news_research` follows."""
        source = Path("app/tools/commentary/tool.py").read_text("utf-8")

        for forbidden in ("sentiment", "score", "rating", "bullish", "bearish"):
            assert forbidden not in source.lower().replace("judgement", "")
