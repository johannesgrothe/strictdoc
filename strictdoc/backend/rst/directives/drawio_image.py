import os
import re
import struct
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from docutils import nodes
from docutils.parsers.rst import directives
from docutils.parsers.rst.directives.images import Image
from py_draw_io.cell_collection import CellNotFoundError, IllegalBoundaryError
from py_draw_io.document import Document, NoDrawioDocumentError
from py_draw_io.exporter import (
    DrawIoExporter,
    ExportFailedError,
    IllegalExtensionError,
    LayerConfigurationError,
)

from strictdoc.backend.rst.directives.wildcard_enhanced_image import (
    STRICTDOC_FLAT_ASSETS_SETTING,
    STRICTDOC_REFERENCE_PATH_SETTING,
)


class DrawioImage(Image):  # type: ignore[misc]
    option_spec = Image.option_spec | {
        "page": directives.unchanged,
        "limit": directives.unchanged,
    }

    MAX_VIEWPORT_IMAGE_HEIGHT = 60

    @classmethod
    def _read_png_size(cls, png_file: Path) -> Tuple[int, int]:
        """
        Reads the pixel dimensions of a PNG file from its header.

        :param png_file: PNG file to read
        :return: The width and height in pixels
        :raises ValueError: If the file is not a PNG file
        """
        # A PNG starts with an 8-byte signature followed by the IHDR chunk, which
        # stores the image width and height as big-endian 32-bit integers.
        with open(png_file, "rb") as file:
            header = file.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            raise ValueError(f"not a PNG file: {png_file}")
        width, height = struct.unpack(">II", header[16:24])
        return width, height

    @classmethod
    def _slug(cls, value: str) -> str:
        """
        Converts a value into a lowercase string that is safe to use in a
        file name.

        :param value: Value to convert, e.g. a page name or cell id
        :return: The slug, or "page" if nothing usable is left of the value
        """
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-").lower()
        return slug if len(slug) > 0 else "page"

    @classmethod
    def _get_viewport_image_height(cls, png_file: Path) -> int:
        """
        Calculates the image height relative to the browser viewport, based on
        the aspect ratio of the exported image.

        :param png_file: Exported PNG file
        :return: The calculated height in vh (percent of the viewport height),
            at most MAX_VIEWPORT_IMAGE_HEIGHT
        """
        width, height = cls._read_png_size(png_file)
        # Taller images (smaller aspect ratio) get more of the viewport,
        # capped so that no diagram takes up most of the screen.
        return min(
            cls.MAX_VIEWPORT_IMAGE_HEIGHT,
            25 + int((height / width) * 13),
        )

    def run(self) -> Sequence[nodes.Node]:
        """
        Exports a page of a draw.io diagram to PNG and renders it as an image.

        Usage::

            .. drawio-image:: _assets/architecture.drawio
               :page: Overview
               :limit: some-cell-id

        :return: The image nodes, or an empty list if the diagram could not
            be exported
        """
        # We render the diagram here, not in the exported .drawio file
        # itself: shell out to a locally installed draw.io desktop app (via
        # py_draw_io.exporter.DrawIoExporter) to turn one page of the diagram
        # into a PNG, then rewrite self.arguments[0] to point at that PNG and
        # delegate to the base Image directive, exactly like
        # WildcardEnhancedImage does for its own path rewriting.
        assert len(self.arguments) > 0

        current_reference_path = getattr(
            self.state.document.settings,
            STRICTDOC_REFERENCE_PATH_SETTING,
            os.getcwd(),
        )
        flat_assets = getattr(
            self.state.document.settings,
            STRICTDOC_FLAT_ASSETS_SETTING,
            False,
        )

        rel_path_to_drawio = self.arguments[0]
        # See WildcardEnhancedImage for why this rebasing is needed in
        # flat_assets (bundle) mode.
        if flat_assets:
            while rel_path_to_drawio.startswith("../"):
                rel_path_to_drawio = rel_path_to_drawio[3:]

        full_path_to_drawio = Path(os.path.normpath(
            os.path.join(current_reference_path, rel_path_to_drawio)
        ))

        page_option: Optional[str] = self.options.get("page")
        limit_option: Optional[str] = self.options.get("limit")
        try:
            document = Document.load(full_path_to_drawio)
            page = page_option or document.diagrams[0].name
        except (NoDrawioDocumentError, IndexError) as exception:
            return self._error(f"drawio-image: {exception}")

        variant_slug = self._slug(page)
        if limit_option is not None:
            variant_slug = f"{variant_slug}__{self._slug(limit_option)}"

        source_dir, source_file_name = os.path.split(rel_path_to_drawio)
        source_stem = source_file_name.rsplit(".", 1)[0]
        target_file_name = f"{source_stem}__{variant_slug}.png"
        target_rel_path = (
            os.path.join(source_dir, target_file_name)
            if len(source_dir) > 0
            else target_file_name
        )
        full_target_path = os.path.normpath(
            os.path.join(current_reference_path, target_rel_path)
        )

        # No draw_io= override and no custom temp_dir/use_cache: DrawIoExporter
        # falls back to its own defaults (a locally installed draw.io desktop
        # app discoverable on its own, e.g. via PATH; no caching between runs).
        try:
            DrawIoExporter().export(
                source=full_path_to_drawio,
                page=page,
                out_path=Path(full_target_path),
                limit_export=limit_option,
            )
            height = self._get_viewport_image_height(Path(full_target_path))
        except (
                ExportFailedError,
                LayerConfigurationError,
                IllegalExtensionError,
                CellNotFoundError,
                IllegalBoundaryError,
                FileNotFoundError,
                ValueError,
        ) as exception:
            return self._error(
                f"drawio-image: failed to export '{rel_path_to_drawio}' "
                f"(page '{page}', limit '{limit_option}'): {exception}"
            )

        self.arguments[0] = target_rel_path
        self.options.setdefault("height", f"{height}vh")

        messages: Sequence[nodes.Node] = super().run()
        return messages

    def _error(self, message: str) -> List[nodes.Node]:
        """
        Reports an error at the directive's line in the RST source.

        :param message: Error message to report
        :return: An empty list of nodes, so that nothing is rendered
        """
        self.state_machine.reporter.error(message, line=self.lineno)
        return []
