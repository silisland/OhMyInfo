"""
Tests for src/collectors/arxiv.py — arXiv paper collector.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from pytest_httpx import HTTPXMock

from src.collectors import Article, CollectorError
from src.collectors.arxiv import ArxivCollector, _extract_arxiv_id, _parse_arxiv_date

# ------------------------------------------------------------------
# Fixtures — realistic arXiv Atom XML samples
# ------------------------------------------------------------------

SINGLE_ENTRY_ATOM = """\
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <title>   Attention Is All You Need But Better: A New Architecture
    </title>
    <published>2024-01-15T18:30:00Z</published>
    <summary>
      This paper proposes a novel neural architecture that improves upon
      the original Transformer by introducing a more efficient attention
      mechanism. Our method achieves state-of-the-art results on multiple
      benchmarks while reducing computational cost by 30%.
    </summary>
    <author>
      <name>John Doe</name>
    </author>
    <author>
      <name>Jane Smith</name>
    </author>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom"
        term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.AI"
        scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG"
        scheme="http://arxiv.org/schemas/atom"/>
    <link href="http://arxiv.org/abs/2401.12345v1" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2401.12345v1" rel="related"
        type="application/pdf" title="pdf"/>
  </entry>
</feed>"""

MULTI_ENTRY_ATOM = """\
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.10001v1</id>
    <title>First Paper Title</title>
    <published>2024-01-14T10:00:00Z</published>
    <summary>Abstract of the first paper.</summary>
    <author>
      <name>Alice Wang</name>
    </author>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom"
        term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.CL"
        scheme="http://arxiv.org/schemas/atom"/>
    <link href="http://arxiv.org/abs/2401.10001v1" rel="alternate" type="text/html"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.10002v2</id>
    <title>Second Paper Title</title>
    <published>2024-01-14T11:00:00Z</published>
    <summary>Abstract of the second paper, which is slightly longer
      and contains multiple lines of text describing the method.</summary>
    <author>
      <name>Bob Chen</name>
    </author>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom"
        term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG"
        scheme="http://arxiv.org/schemas/atom"/>
    <link href="http://arxiv.org/abs/2401.10002v2" rel="alternate" type="text/html"/>
  </entry>
</feed>"""

EMPTY_FEED_ATOM = """\
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>arXiv Search Results</title>
  <entry/>
</feed>"""

MALFORMED_XML = """\
this is not valid xml at all <<>>"""


# ------------------------------------------------------------------
# Helper: build mock response
# ------------------------------------------------------------------


def _mock_response(xml_content: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        text=xml_content,
        headers={"Content-Type": "application/atom+xml"},
    )


# ------------------------------------------------------------------
# ArxivCollector Tests
# ------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
class TestArxivCollector:
    """ArxivCollector integration tests with mocked HTTP."""

    async def test_fetch_single_category_single_entry(
        self, httpx_mock: HTTPXMock
    ) -> None:
        """Fetch from one category returns one article."""
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=10&sortBy=submittedDate&sortOrder=descending",
            text=SINGLE_ENTRY_ATOM,
        )

        collector = ArxivCollector(categories=["cs.AI"], max_results=10)
        articles = await collector.fetch()

        assert len(articles) == 1
        article = articles[0]
        assert article.title == "Attention Is All You Need But Better: A New Architecture"
        assert article.url == "https://arxiv.org/abs/2401.12345"
        assert article.source == "arxiv"
        assert article.author == "John Doe, Jane Smith"
        assert article.category == "cs.AI"
        assert "novel neural architecture" in article.content
        assert "cs.AI" in article.tags
        assert "John Doe" in article.tags
        assert "Jane Smith" in article.tags

    async def test_fetch_multiple_entries(self, httpx_mock: HTTPXMock) -> None:
        """Fetch returns all entries from the feed."""
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.CL&max_results=10&sortBy=submittedDate&sortOrder=descending",
            text=MULTI_ENTRY_ATOM,
        )

        collector = ArxivCollector(categories=["cs.CL"], max_results=10)
        articles = await collector.fetch()

        assert len(articles) == 2
        assert articles[0].title == "First Paper Title"
        assert articles[1].title == "Second Paper Title"
        assert articles[0].category == "cs.CL"
        assert articles[1].category == "cs.LG"

    async def test_fetch_multiple_categories(self, httpx_mock: HTTPXMock) -> None:
        """Fetch across multiple categories aggregates articles."""
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=10&sortBy=submittedDate&sortOrder=descending",
            text=SINGLE_ENTRY_ATOM,
        )
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.LG&max_results=10&sortBy=submittedDate&sortOrder=descending",
            text=MULTI_ENTRY_ATOM,
        )

        collector = ArxivCollector(categories=["cs.AI", "cs.LG"], max_results=10)
        articles = await collector.fetch()

        # 1 from cs.AI + 2 from cs.LG
        assert len(articles) == 3

    async def test_empty_results(self, httpx_mock: HTTPXMock) -> None:
        """Empty feed returns empty list."""
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=10&sortBy=submittedDate&sortOrder=descending",
            text=EMPTY_FEED_ATOM,
        )

        collector = ArxivCollector(categories=["cs.AI"], max_results=10)
        articles = await collector.fetch()

        assert articles == []

    async def test_empty_categories(self) -> None:
        """No categories returns empty list without making HTTP requests."""
        collector = ArxivCollector(categories=[], max_results=10)
        articles = await collector.fetch()

        assert articles == []

    async def test_http_error_raises_collector_error(self, httpx_mock: HTTPXMock) -> None:
        """HTTP 5xx raises CollectorError."""
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=10&sortBy=submittedDate&sortOrder=descending",
            status_code=503,
        )

        collector = ArxivCollector(categories=["cs.AI"], max_results=10)

        with pytest.raises(CollectorError) as exc_info:
            await collector.fetch()

        assert exc_info.value.source == "arxiv"
        assert "503" in str(exc_info.value)

    async def test_malformed_xml_raises_collector_error(
        self, httpx_mock: HTTPXMock
    ) -> None:
        """Malformed XML with no entries raises CollectorError."""
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=10&sortBy=submittedDate&sortOrder=descending",
            text=MALFORMED_XML,
        )

        collector = ArxivCollector(categories=["cs.AI"], max_results=10)

        with pytest.raises(CollectorError):
            await collector.fetch()

    async def test_partial_failure_all_fail(self, httpx_mock: HTTPXMock) -> None:
        """When all categories fail, CollectorError is raised."""
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=10&sortBy=submittedDate&sortOrder=descending",
            status_code=500,
        )
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.LG&max_results=10&sortBy=submittedDate&sortOrder=descending",
            status_code=500,
        )

        collector = ArxivCollector(categories=["cs.AI", "cs.LG"], max_results=10)

        with pytest.raises(CollectorError) as exc_info:
            await collector.fetch()

        assert "All categories failed" in str(exc_info.value)

    async def test_default_categories(self, httpx_mock: HTTPXMock) -> None:
        """Default categories (cs.AI, cs.LG, cs.CL) are used when none specified."""
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=10&sortBy=submittedDate&sortOrder=descending",
            text=EMPTY_FEED_ATOM,
        )
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.LG&max_results=10&sortBy=submittedDate&sortOrder=descending",
            text=EMPTY_FEED_ATOM,
        )
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.CL&max_results=10&sortBy=submittedDate&sortOrder=descending",
            text=EMPTY_FEED_ATOM,
        )

        collector = ArxivCollector()
        articles = await collector.fetch()

        assert articles == []

    async def test_network_error_raises_collector_error(
        self, httpx_mock: HTTPXMock
    ) -> None:
        """Network-level errors (connection refused, DNS failure) raise CollectorError."""
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=10&sortBy=submittedDate&sortOrder=descending",
        )

        collector = ArxivCollector(categories=["cs.AI"], max_results=10)

        with pytest.raises(CollectorError) as exc_info:
            await collector.fetch()

        assert exc_info.value.source == "arxiv"

    async def test_name_property(self) -> None:
        """name returns 'arxiv'."""
        collector = ArxivCollector()
        assert collector.name == "arxiv"

    async def test_default_health(self) -> None:
        """health() returns expected structure."""
        collector = ArxivCollector()
        health = collector.health()

        assert health["name"] == "arxiv"
        assert health["status"] == "ok"
        assert health["timeout"] == 30
        assert health["max_retries"] == 3

    async def test_custom_max_results(self, httpx_mock: HTTPXMock) -> None:
        """Custom max_results is reflected in the API URL."""
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=5&sortBy=submittedDate&sortOrder=descending",
            text=SINGLE_ENTRY_ATOM,
        )

        collector = ArxivCollector(categories=["cs.AI"], max_results=5)
        articles = await collector.fetch()

        assert len(articles) == 1

    async def test_summary_truncated_to_300_chars(self, httpx_mock: HTTPXMock) -> None:
        """Summary field is truncated to 300 characters."""
        long_abstract = "A" * 500
        atom = f"""\
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.99999v1</id>
    <title>Long Abstract Paper</title>
    <published>2024-01-15T18:30:00Z</published>
    <summary>{long_abstract}</summary>
    <author><name>Test Author</name></author>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom"
        term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.AI"
        scheme="http://arxiv.org/schemas/atom"/>
    <link href="http://arxiv.org/abs/2401.99999v1" rel="alternate" type="text/html"/>
  </entry>
</feed>"""
        httpx_mock.add_response(
            url="http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=10&sortBy=submittedDate&sortOrder=descending",
            text=atom,
        )

        collector = ArxivCollector(categories=["cs.AI"], max_results=10)
        articles = await collector.fetch()

        assert len(articles) == 1
        assert len(articles[0].summary) <= 300
        assert articles[0].summary == long_abstract[:300]
        # Full abstract stored in content
        assert len(articles[0].content) == 500


# ------------------------------------------------------------------
# _extract_arxiv_id tests
# ------------------------------------------------------------------


class TestExtractArxivId:
    """Unit tests for _extract_arxiv_id helper."""

    def test_full_abstract_url(self) -> None:
        assert _extract_arxiv_id("http://arxiv.org/abs/2401.12345v1") == "2401.12345"

    def test_full_abstract_url_no_version(self) -> None:
        assert _extract_arxiv_id("http://arxiv.org/abs/2401.12345") == "2401.12345"

    def test_pdf_url(self) -> None:
        assert _extract_arxiv_id("http://arxiv.org/pdf/2401.54321v1") == "2401.54321"

    def test_raw_id_with_version(self) -> None:
        assert _extract_arxiv_id("2401.67890v1") == "2401.67890"

    def test_raw_id_no_version(self) -> None:
        assert _extract_arxiv_id("2401.67890") == "2401.67890"

    def test_new_format_id(self) -> None:
        """arXiv new format IDs (5+ digits) are handled."""
        assert _extract_arxiv_id("2401.123456v1") == "2401.123456"

    def test_old_format_id(self) -> None:
        """Old arXiv format IDs are handled."""
        assert _extract_arxiv_id("http://arxiv.org/abs/cs/0702115v1") == "cs/0702115"


# ------------------------------------------------------------------
# _parse_arxiv_date tests
# ------------------------------------------------------------------


class TestParseArxivDate:
    """Unit tests for _parse_arxiv_date helper."""

    def test_iso_date_with_z(self) -> None:
        dt = _parse_arxiv_date("2024-01-15T18:30:00Z")
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 18
        assert dt.minute == 30
        assert dt.tzinfo is not None

    def test_empty_string_returns_now(self) -> None:
        dt = _parse_arxiv_date("")
        # Should return current UTC datetime
        assert isinstance(dt, datetime)
        assert dt.tzinfo is not None

    def test_invalid_string_returns_now(self) -> None:
        dt = _parse_arxiv_date("not-a-date")
        assert isinstance(dt, datetime)
        assert dt.tzinfo is not None
