import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import List, Optional

from docutils import nodes
from docutils.parsers.rst import directives
from docutils.parsers.rst.directives.images import Image
from py_draw_io import SETTINGS
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

STRICTDOC_DRAWIO_CACHE_DIR_SETTING = "strictdoc_drawio_cache_dir"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-").lower()
    return slug if len(slug) > 0 else "page"


class DrawioImage(Image):  # type: ignore[misc]
    option_spec = {
        **Image.option_spec,
        "page": directives.unchanged,
        "limit": directives.unchanged,
    }

    def run(self) -> List[nodes.Node]:
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
        cache_dir = getattr(
            self.state.document.settings,
            STRICTDOC_DRAWIO_CACHE_DIR_SETTING,
            None,
        )

        rel_path_to_drawio = self.arguments[0]
        # See WildcardEnhancedImage for why this rebasing is needed in
        # flat_assets (bundle) mode.
        if flat_assets:
            while rel_path_to_drawio.startswith("../"):
                rel_path_to_drawio = rel_path_to_drawio[3:]

        full_path_to_drawio = os.path.normpath(
            os.path.join(current_reference_path, rel_path_to_drawio)
        )

        if not os.path.isfile(full_path_to_drawio):
            return self._error(
                f"drawio-image: file not found: {rel_path_to_drawio}"
            )
        if not full_path_to_drawio.endswith((".drawio", ".xml")):
            return self._error(
                "drawio-image: expected a .drawio or .xml file, got: "
                f"{rel_path_to_drawio}"
            )

        page_option: Optional[str] = self.options.get("page")
        limit_option: Optional[str] = self.options.get("limit")
        try:
            document = Document.load(Path(full_path_to_drawio))
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

        try:
            cached_png_path = self._export_cached(
                full_path_to_drawio,
                page,
                limit_option,
                variant_slug,
                cache_dir,
            )
        except (
            ExportFailedError,
            LayerConfigurationError,
            IllegalExtensionError,
            CellNotFoundError,
            IllegalBoundaryError,
            FileNotFoundError,
        ) as exception:
            return self._error(
                f"drawio-image: failed to export '{rel_path_to_drawio}' "
                f"(page '{page}', limit '{limit_option}'): {exception}"
            )

        os.makedirs(os.path.dirname(full_target_path) or ".", exist_ok=True)
        shutil.copyfile(cached_png_path, full_target_path)

        self.arguments[0] = target_rel_path

        messages: List[nodes.Node] = super().run()
        return messages

    @staticmethod
    def _export_cached(
        full_path_to_drawio: str,
        page: str,
        limit_export: Optional[str],
        variant_slug: str,
        cache_dir: Optional[str],
    ) -> Path:
        assert cache_dir is not None
        drawio_cache_dir = Path(cache_dir) / "drawio"
        SETTINGS.switch_cache_file(drawio_cache_dir / ".py_draw_io_cache")

        source_hash = hashlib.md5(
            full_path_to_drawio.encode("utf-8")
        ).hexdigest()
        cached_png_path = (
            drawio_cache_dir / "rendered" / source_hash / f"{variant_slug}.png"
        )

        # No draw_io= override: DrawIoExporter falls back to its own default
        # (a locally installed draw.io desktop app discoverable on its own,
        # e.g. via PATH).
        exporter = DrawIoExporter(
            temp_dir=drawio_cache_dir / "tmp",
            use_cache=True,
        )
        exporter.export(
            source=Path(full_path_to_drawio),
            page=page,
            out_path=cached_png_path,
            limit_export=limit_export,
        )
        return cached_png_path

    def _error(self, message: str) -> List[nodes.Node]:
        self.state_machine.reporter.error(message, line=self.lineno)
        return []
