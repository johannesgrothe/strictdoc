import os
import re
from pathlib import Path
from typing import List, Optional, Sequence

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
from py_draw_io.geometry_cell import GeometryCell

from strictdoc.backend.rst.directives.wildcard_enhanced_image import (
    STRICTDOC_FLAT_ASSETS_SETTING,
    STRICTDOC_REFERENCE_PATH_SETTING,
)


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-").lower()
    return slug if len(slug) > 0 else "page"


class DrawioImage(Image):  # type: ignore[misc]
    option_spec = Image.option_spec | {
        "page": directives.unchanged,
        "limit": directives.unchanged,
    }

    MAX_VIEWPORT_IMAGE_HEIGHT = 60

    @classmethod
    def _get_viewport_image_height(cls, source_file: Path, page: str, element_id: Optional[str]) -> int:
        """
        Calculates the image height relative to the browser viewport
        """
        if element_id is None:
            return cls.MAX_VIEWPORT_IMAGE_HEIGHT

        diagram = Document.load(source_file).get_diagram(page)
        limit_geometry = diagram.find_by_id(element_id)

        if not isinstance(limit_geometry, GeometryCell):
            raise ValueError(
                f"limit geometry ({element_id}) is no geometry element"
            )
        # Taller elements (smaller aspect ratio) get more of the viewport,
        # capped so that no diagram takes up most of the screen.
        return min(
            cls.MAX_VIEWPORT_IMAGE_HEIGHT,
            25 + int((1 / limit_geometry.aspect_ratio) * 13),
        )

    def run(self) -> Sequence[nodes.Node]:
        # """
        # .. drawio-image:: _assets/architecture.drawio
        #    :page: Overview
        #    :limit: some-cell-id
        # """
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

        variant_slug = _slug(page)
        if limit_option is not None:
            variant_slug = f"{variant_slug}__{_slug(limit_option)}"

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
            height = self._get_viewport_image_height(
                full_path_to_drawio, page, limit_option
            )

            DrawIoExporter().export(
                source=full_path_to_drawio,
                page=page,
                out_path=Path(full_target_path),
                limit_export=limit_option,
            )
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
        self.state_machine.reporter.error(message, line=self.lineno)
        return []
