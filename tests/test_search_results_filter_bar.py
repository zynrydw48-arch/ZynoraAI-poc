import sys

import pytest
from PySide6.QtWidgets import QApplication

from memoryos.ui.search_results_filter_bar import SearchResultsFilterBar, categorize_extension

_app = QApplication.instance() or QApplication(sys.argv)


@pytest.mark.parametrize(
    "extension,expected",
    [
        (".png", "Images"),
        (".jpg", "Images"),
        (".JPG", "Images"),  # case-insensitivity
        (".webp", "Images"),
        (".html", "Web"),
        (".htm", "Web"),
        (".url", "Web"),
        (".pdf", "Files"),
        (".docx", "Files"),
        (".xlsx", "Files"),
        (".pptx", "Files"),
        (".zip", "Files"),
        (".txt", "Files"),
        (".csv", "Files"),
        (".eml", "Email"),
        (".msg", "Email"),
        (".MSG", "Email"),  # case-insensitivity
        (".md", "Notes"),
        (".markdown", "Notes"),
        (".norg", "Notes"),
        (".org", "Notes"),
        (".exe", "More..."),
        ("", "More..."),
    ],
)
def test_categorize_extension(extension, expected):
    assert categorize_extension(extension) == expected


def test_categorize_extension_accepts_extension_without_leading_dot():
    assert categorize_extension("PNG") == "Images"


def test_all_tab_checked_by_default():
    bar = SearchResultsFilterBar()
    assert bar._buttons["All"].isChecked()
    for label, button in bar._buttons.items():
        if label != "All":
            assert not button.isChecked()


def test_clicking_a_tab_makes_it_exclusively_checked():
    bar = SearchResultsFilterBar()
    bar._buttons["Images"].click()

    assert bar._buttons["Images"].isChecked()
    assert not bar._buttons["All"].isChecked()


def test_clicking_a_tab_emits_filter_selected():
    bar = SearchResultsFilterBar()
    received = []
    bar.filter_selected.connect(received.append)

    bar._buttons["Web"].click()

    assert received == ["Web"]


def test_reset_restores_all_tab():
    bar = SearchResultsFilterBar()
    bar._buttons["Notes"].click()
    assert bar._buttons["Notes"].isChecked()

    bar.reset()

    assert bar._buttons["All"].isChecked()
    assert not bar._buttons["Notes"].isChecked()
