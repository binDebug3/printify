"""Tests for printify_api_tools/get_base_mockups.py."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from unittest.mock import patch
import pytest

from src.printify_api_tools import get_base_mockups


class TestNaming:
    """Tests for naming behavior."""

    def test_to_camel_case(self) -> None:
        """Converts input text to lower camelCase."""
        assert get_base_mockups.to_camel_case("Light Blue") == "lightBlue"

    def test_assign_filenames_uses_color_then_fallback(self) -> None:
        """Uses color-based names and numbered mockup fallback names."""
        mockups: List[Tuple[str, Optional[str]]] = [
            ("https://a", "Dark Gray"),
            ("https://b", None),
            ("https://c", "Dark Gray"),
            ("https://d", None),
        ]

        result = get_base_mockups.assign_filenames(mockups)
        assert result == [
            ("https://a", "darkGray"),
            ("https://b", "mockup1"),
            ("https://c", "darkGray2"),
            ("https://d", "mockup2"),
        ]


class TestSaveMockups:
    """Tests for end-to-end save flow with mocked network calls."""

    def test_save_mockups_writes_links_and_downloads(self, tmp_path: Path) -> None:
        """Writes links file and downloads each mockup image with expected names."""
        product: Dict = {
            "images": [
                {"src": "https://example.com/pid/111/one.png"},
                {"src": "https://example.com/pid/222/two.png"},
                {"src": "https://example.com/pid/no-variant/three.png"},
            ],
        }

        links_path = tmp_path / "links.txt"
        out_dir = tmp_path / "images"

        with (
            patch.object(get_base_mockups, "fetch_product", return_value=product),
            patch.object(get_base_mockups, "load_shop_id", return_value="sid"),
            patch.object(get_base_mockups, "load_api_token", return_value="tok"),
            patch.object(
                get_base_mockups,
                "load_variant_color_map",
                return_value={111: "Ocean Blue", 222: "Sunset Orange"},
            ),
            patch.object(get_base_mockups, "LINKS_FILE", links_path),
            patch.object(get_base_mockups, "OUTPUT_DIR", out_dir),
            patch.object(get_base_mockups, "download_image") as mock_download,
        ):
            paths = get_base_mockups.save_mockups("pid")

        assert links_path.exists()
        assert links_path.read_text(encoding="utf-8").splitlines() == [
            "https://example.com/pid/111/one.png",
            "https://example.com/pid/222/two.png",
            "https://example.com/pid/no-variant/three.png",
        ]
        assert [p.name for p in paths] == [
            "oceanBlue.png",
            "sunsetOrange.png",
            "mockup1.png",
        ]
        assert mock_download.call_count == 3

    def test_write_links_file_appends(self, tmp_path: Path) -> None:
        """Appends links to links.txt rather than replacing previous content."""
        links_path = tmp_path / "links.txt"
        links_path.write_text("https://existing\n", encoding="utf-8")

        get_base_mockups.write_links_file(
            ["https://new-1", "https://new-2"], links_path
        )

        assert links_path.read_text(encoding="utf-8").splitlines() == [
            "https://existing",
            "https://new-1",
            "https://new-2",
        ]

    def test_save_mockups_renames_on_existing_images(self, tmp_path: Path) -> None:
        """Downloads images using a new filename when a conflict already exists."""
        product: Dict = {
            "images": [{"src": "https://example.com/pid/111/one.png"}],
        }

        links_path = tmp_path / "links.txt"
        out_dir = tmp_path / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        existing_image = out_dir / "oceanBlue.png"
        existing_image.write_bytes(b"already-there")

        with (
            patch.object(get_base_mockups, "fetch_product", return_value=product),
            patch.object(get_base_mockups, "load_shop_id", return_value="sid"),
            patch.object(get_base_mockups, "load_api_token", return_value="tok"),
            patch.object(
                get_base_mockups,
                "load_variant_color_map",
                return_value={111: "Ocean Blue"},
            ),
            patch.object(get_base_mockups, "LINKS_FILE", links_path),
            patch.object(get_base_mockups, "OUTPUT_DIR", out_dir),
            patch.object(get_base_mockups, "download_image") as mock_download,
        ):
            paths = get_base_mockups.save_mockups("pid")

        assert [path.name for path in paths] == ["oceanBlue2.png"]
        assert mock_download.call_count == 1
        assert mock_download.call_args[0][1].name == "oceanBlue2.png"
        assert existing_image.read_bytes() == b"already-there"

    def test_extract_variant_id_from_link_after_product_id(self) -> None:
        """Parses variant id from URL segment immediately after product_id."""
        url = "https://example.com/assets/pid/73199/mockup.png"
        variant_id = get_base_mockups.extract_variant_id_from_link(url, "pid")
        assert variant_id == 73199

    def test_download_mockups_from_links_file(self, tmp_path: Path) -> None:
        """Downloads all links and names files by color via variant map lookup."""
        links_path = tmp_path / "links.txt"
        links_path.write_text(
            "https://example.com/assets/24946802/73199/a.png\n"
            "https://example.com/assets/24946802/73196/b.png\n",
            encoding="utf-8",
        )
        out_dir = tmp_path / "images"

        with (
            patch.object(
                get_base_mockups,
                "load_variant_color_map",
                return_value={73199: "White", 73196: "Black"},
            ),
            patch.object(get_base_mockups, "download_image") as mock_download,
        ):
            paths = get_base_mockups.download_mockups_from_links_file(
                links_path=links_path,
                output_dir=out_dir,
            )

        assert [path.name for path in paths] == ["white.png", "black.png"]
        assert mock_download.call_count == 2

    def test_download_mockups_from_links_file_fallback_name(
        self, tmp_path: Path
    ) -> None:
        """Uses numbered fallback names when variant id cannot be mapped."""
        links_path = tmp_path / "links.txt"
        links_path.write_text(
            "https://example.com/assets/no-id/a.png\n",
            encoding="utf-8",
        )
        out_dir = tmp_path / "images"

        with (
            patch.object(get_base_mockups, "load_variant_color_map", return_value={}),
            patch.object(get_base_mockups, "download_image") as mock_download,
        ):
            paths = get_base_mockups.download_mockups_from_links_file(
                links_path=links_path,
                output_dir=out_dir,
            )

        assert [path.name for path in paths] == ["mockup1.png"]
        assert mock_download.call_count == 1


class TestCliMode:
    """Tests for get_base_mockups CLI mode selection."""

    def test_main_uses_from_links_mode(self) -> None:
        """Runs links-file downloader when --from-links flag is set."""
        with (
            patch.object(
                get_base_mockups,
                "parse_args",
                return_value=type(
                    "Args", (), {"from_links": True, "product_id": None}
                )(),
            ),
            patch.object(
                get_base_mockups,
                "download_mockups_from_links_file",
                return_value=[],
            ) as mock_from_links,
            patch.object(get_base_mockups, "save_mockups") as mock_save,
        ):
            get_base_mockups.main()

        mock_from_links.assert_called_once()
        mock_save.assert_not_called()

    def test_main_requires_product_id_without_from_links(self) -> None:
        """Raises when product_id is missing and --from-links is not set."""
        with patch.object(
            get_base_mockups,
            "parse_args",
            return_value=type("Args", (), {"from_links": False, "product_id": None})(),
        ):
            with pytest.raises(ValueError, match="product_id is required"):
                get_base_mockups.main()
