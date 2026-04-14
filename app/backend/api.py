import os
import webview
from app.backend.extraction_runner import ExtractionRunner
from app.backend import file_utils
from term_extractor.model_lang_maps import SPACY_LANG_SUPPORT, NLTK_LANG_SUPPORT, LABSE_LANG_SUPPORT

LANGUAGE_NAMES = {
    'ar': 'Arabic', 'en': 'English', 'it': 'Italian',
    'de': 'German', 'fr': 'French',
}


class TermExtractorAPI:
    """Python API class exposed to JavaScript via pywebview."""

    def __init__(self):
        self._window = None
        self._runner = ExtractionRunner()
        self._last_result_path = ""
        self._output_dir = ""

    def set_window(self, window):
        self._window = window

    # ==================== Setup ====================

    def get_supported_languages(self) -> dict:
        """Returns language options for dropdowns."""
        valid = {code: LANGUAGE_NAMES.get(code, code.upper())
                 for code in NLTK_LANG_SUPPORT
                 if code in LABSE_LANG_SUPPORT}
        spacy_codes = list(SPACY_LANG_SUPPORT.keys())
        return {
            "languages": [{"code": k, "name": v} for k, v in sorted(valid.items(), key=lambda x: x[1])],
            "spacy_supported": spacy_codes,
        }

    def get_default_config(self) -> dict:
        """Returns all Extractor defaults."""
        from term_extractor.magic import Extractor
        te = Extractor()
        return {
            "min_source_rep": te.min_source_rep,
            "max_source_rep": te.max_source_rep,
            "min_llm_score": te.min_llm_score,
            "target_dismiss": te.target_dismiss,
            "min_count_ratio": te.min_count_ratio,
            "grouping_min_lev_sim": te.grouping_min_lev_sim,
            "max_sentence_length": te.max_sentence_length,
            "max_translation_pairs": te.max_translation_pairs,
            "skip_top_common_words": te.skip_top_common_words,
            "skip_peri_stop_words": te.skip_peri_stop_words,
            "model": te.model,
            "llm_scoring": te.llm_scoring,
            "enable_partial_points": te.enable_partial_points,
            "src_term_extraction_method": te.src_term_extraction_method,
            "max_1st_cleanup_cand_count": te.max_1st_cleanup_cand_count,
            "max_grouping_cand_count": te.max_grouping_cand_count,
        }

    def browse_csv_file(self) -> str:
        """Open native file dialog for CSV files."""
        if not self._window:
            return ""
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=('CSV Files (*.csv)', 'All Files (*.*)')
        )
        if result and len(result) > 0:
            return result[0]
        return ""

    def browse_output_directory(self) -> str:
        """Open native folder dialog."""
        if not self._window:
            return ""
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return result[0]
        return ""

    def browse_terms_file(self) -> str:
        """Open native file dialog for .txt files."""
        if not self._window:
            return ""
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=('Text Files (*.txt)', 'All Files (*.*)')
        )
        if result and len(result) > 0:
            return result[0]
        return ""

    def browse_json_file(self) -> str:
        """Open native file dialog for .json files."""
        if not self._window:
            return ""
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=('JSON Files (*.json)', 'All Files (*.*)')
        )
        if result and len(result) > 0:
            return result[0]
        return ""

    def browse_excel_save_path(self) -> str:
        """Open native save dialog for Excel files."""
        if not self._window:
            return ""
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename='exported_terms.xlsx',
            file_types=('Excel Files (*.xlsx)', 'All Files (*.*)')
        )
        if result:
            return result
        return ""

    def preview_csv(self, path: str) -> dict:
        """Returns preview info for a CSV file."""
        return file_utils.read_csv_preview(path)

    # ==================== Extraction ====================

    def start_extraction(self, config: dict) -> bool:
        """Launch extraction in background thread."""
        self._output_dir = config.get("output_dir", "")
        return self._runner.start(config)

    def cancel_extraction(self) -> None:
        """Cancel the running extraction."""
        self._runner.cancel()

    def get_extraction_status(self) -> dict:
        """Poll extraction status."""
        status = self._runner.get_status()
        if status.get("is_complete") and status.get("result_path"):
            self._last_result_path = status["result_path"]
        return status

    def get_last_result_path(self) -> str:
        """Get the path of the last extraction result JSON."""
        return self._last_result_path

    # ==================== Editor ====================

    def load_terms_json(self, path: str = "") -> dict:
        """Load terms JSON file."""
        if not path:
            path = self._last_result_path
        if not path:
            return {"success": False, "error": "No path provided"}
        result = file_utils.load_json_file(path)
        if result["success"]:
            self._output_dir = os.path.dirname(path)
        return result

    def save_session(self, unique_id: str, data: dict) -> dict:
        """Save editor session to file."""
        output_dir = self._output_dir or os.path.expanduser("~")
        return file_utils.save_session(output_dir, unique_id, data)

    def load_session(self, unique_id: str) -> dict:
        """Load saved editor session."""
        output_dir = self._output_dir or os.path.expanduser("~")
        return file_utils.load_session(output_dir, unique_id)

    def export_to_excel(self, terms: list, path: str = "") -> dict:
        """Export terms to Excel file."""
        if not path:
            path = self.browse_excel_save_path()
        if not path:
            return {"success": False, "error": "No save path selected"}
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'
        return file_utils.export_to_excel(terms, path)
