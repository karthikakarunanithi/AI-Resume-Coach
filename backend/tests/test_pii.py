import pytest

from app.services.pii import redact_pii


@pytest.mark.parametrize(
    "text",
    [
        "karthika.k@topgeo.ai",
        "+91 98765 43210",
        "+91-98765-43210",
        "9876543210",
        "(044) 2345 6789",
        "https://linkedin.com/in/someone",
        "github.com/someone/repo",
        "www.portfolio.dev",
    ],
)
def test_contact_details_are_redacted(text):
    out = redact_pii(f"Contact: {text} | Chennai")
    assert text not in out
    assert out.startswith("Contact: [") and out.endswith("| Chennai")


@pytest.mark.parametrize(
    "text",
    [
        "2019-2023",
        "Jan 2020 - Mar 2023",
        "CGPA 8.5/10",
        "Reduced latency by 40% (1200 ms to 720 ms)",
        "Python 3.11",
    ],
)
def test_non_contact_numbers_are_kept(text):
    assert redact_pii(text) == text
