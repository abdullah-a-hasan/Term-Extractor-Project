import threading
import time
import builtins

from term_extractor.magic import Extractor


class ExtractionRunner:
    """Runs Extractor in a background thread and provides status polling."""

    STEPS = [
        "Preparing source terms",
        "Pairing source/target",
        "Sorting candidates",
        "Grouping variants",
        "LLM Scoring",
        "Final cleanup",
    ]

    def __init__(self):
        self._thread = None
        self._cancelled = False
        self._status = {
            "step": 0,
            "step_name": "",
            "progress_pct": 0,
            "log_lines": [],
            "is_running": False,
            "is_complete": False,
            "is_error": False,
            "error_msg": "",
            "result_path": "",
            "start_time": None,
            "elapsed_seconds": 0,
            "terms_count": 0,
        }
        self._lock = threading.Lock()
        self._original_print = builtins.print

    def _log(self, message: str):
        with self._lock:
            self._status["log_lines"].append(message)
            if len(self._status["log_lines"]) > 500:
                self._status["log_lines"] = self._status["log_lines"][-500:]

    def _set_step(self, step_index: int):
        with self._lock:
            self._status["step"] = step_index
            self._status["step_name"] = self.STEPS[step_index] if step_index < len(self.STEPS) else ""
            self._status["progress_pct"] = int((step_index / len(self.STEPS)) * 100)

    def _update_elapsed(self):
        if self._status["start_time"]:
            self._status["elapsed_seconds"] = int(time.time() - self._status["start_time"])

    def get_status(self) -> dict:
        with self._lock:
            self._update_elapsed()
            return dict(self._status)

    def cancel(self):
        self._cancelled = True

    def start(self, config: dict) -> bool:
        """Launch extraction in a background thread."""
        if self._status["is_running"]:
            return False

        with self._lock:
            self._status = {
                "step": 0,
                "step_name": self.STEPS[0],
                "progress_pct": 0,
                "log_lines": [],
                "is_running": True,
                "is_complete": False,
                "is_error": False,
                "error_msg": "",
                "result_path": "",
                "start_time": time.time(),
                "elapsed_seconds": 0,
                "terms_count": 0,
            }
        self._cancelled = False

        self._thread = threading.Thread(target=self._run, args=(config,), daemon=True)
        self._thread.start()
        return True

    def _run(self, config: dict):
        """Main extraction logic running in background thread."""
        original_print = builtins.print

        def custom_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            self._log(msg)
            try:
                original_print(*args, **kwargs)
            except Exception:
                pass

        builtins.print = custom_print

        try:
            te = Extractor()

            if "min_source_rep" in config:
                te.min_source_rep = int(config["min_source_rep"])
            if "max_source_rep" in config:
                te.max_source_rep = int(config["max_source_rep"])
            if "min_llm_score" in config:
                te.min_llm_score = float(config["min_llm_score"])
            if "target_dismiss" in config:
                te.target_dismiss = int(config["target_dismiss"])
            if "min_count_ratio" in config:
                te.min_count_ratio = float(config["min_count_ratio"])
            if "grouping_min_lev_sim" in config:
                te.grouping_min_lev_sim = float(config["grouping_min_lev_sim"])
            if "max_sentence_length" in config:
                te.max_sentence_length = int(config["max_sentence_length"])
            if "max_translation_pairs" in config:
                te.max_translation_pairs = int(config["max_translation_pairs"])
            if "skip_top_common_words" in config:
                te.skip_top_common_words = int(config["skip_top_common_words"])
            if "skip_peri_stop_words" in config:
                te.skip_peri_stop_words = bool(config["skip_peri_stop_words"])
            if "model" in config:
                te.model = config["model"]
            if "llm_scoring" in config:
                te.llm_scoring = bool(config["llm_scoring"])
            if "enable_partial_points" in config:
                te.enable_partial_points = bool(config["enable_partial_points"])
            if "src_term_extraction_method" in config:
                te.src_term_extraction_method = config["src_term_extraction_method"]
            if "max_1st_cleanup_cand_count" in config:
                te.max_1st_cleanup_cand_count = int(config["max_1st_cleanup_cand_count"])
            if "max_grouping_cand_count" in config:
                te.max_grouping_cand_count = int(config["max_grouping_cand_count"])

            pred_terms_file = config.get("pred_terms_file", "")
            if pred_terms_file:
                self._log(f"Loading predefined terms from {pred_terms_file}")
                te.load_pred_src_terms(pred_terms_file)

            csv_file = config["csv_file"]
            src_lang = config["src_lang"]
            tar_lang = config["tar_lang"]
            output_dir = config["output_dir"]
            output_name = config.get("output_name", "extracted_terms")

            import os
            output_excel = os.path.join(output_dir, f"{output_name}.xlsx")

            self._log(f"Loading translations from {csv_file}...")
            self._set_step(0)
            te.load_translations(csv_file, src_lang, tar_lang)

            if self._cancelled:
                self._log("Extraction cancelled.")
                with self._lock:
                    self._status["is_running"] = False
                    self._status["is_complete"] = False
                return

            original_prep = te._prep_src_terms
            original_pair = te._pair_src_tar_terms
            original_sort = te._sort_tar_candidates
            original_group = te._candidate_grouping
            original_llm = te._score_with_llm
            original_flag = te._flag_low_scoring_src_terms

            runner = self

            def wrap_step(method, step_idx):
                def wrapper(*args, **kwargs):
                    runner._set_step(step_idx)
                    runner._log(f"Step {step_idx + 1}: {runner.STEPS[step_idx]}...")
                    result = method(*args, **kwargs)
                    runner._set_step(step_idx + 1 if step_idx + 1 < len(runner.STEPS) else step_idx)
                    return result
                return wrapper

            te._prep_src_terms = wrap_step(original_prep, 0)
            te._pair_src_tar_terms = wrap_step(original_pair, 1)
            te._sort_tar_candidates = wrap_step(original_sort, 2)
            te._candidate_grouping = wrap_step(original_group, 3)
            te._score_with_llm = wrap_step(original_llm, 4)
            te._flag_low_scoring_src_terms = wrap_step(original_flag, 5)

            self._log(f"Starting term extraction...")
            report = te.match_terms(output_excel, json_report=True, html_editor=False)

            if self._cancelled:
                self._log("Extraction cancelled after completion (result may be partial).")
            else:
                json_path = os.path.splitext(output_excel)[0] + ".json"
                terms_count = report.get("terms count", 0) if report else 0
                self._log(f"\nExtraction complete! Found {terms_count} terms.")
                self._log(f"Results saved to: {output_excel}")
                with self._lock:
                    self._status["is_complete"] = True
                    self._status["progress_pct"] = 100
                    self._status["result_path"] = json_path
                    self._status["terms_count"] = terms_count

        except Exception as e:
            import traceback
            error_msg = traceback.format_exc()
            self._log(f"ERROR: {str(e)}")
            self._log(error_msg)
            with self._lock:
                self._status["is_error"] = True
                self._status["error_msg"] = str(e)
        finally:
            builtins.print = original_print
            with self._lock:
                self._status["is_running"] = False
