import csv
import functools
import html
import json
import random
import re
import string
from pathlib import Path
import importlib.resources
import shutil

from Levenshtein import distance
from wordfreq import top_n_list
from openpyxl import Workbook
from openpyxl.worksheet.datavalidation import DataValidation

from term_extractor.nlp_lib import NLPTasks, LLMCompare
from term_extractor.model_lang_maps import SPACY_LANG_SUPPORT, NLTK_LANG_SUPPORT, LABSE_LANG_SUPPORT


# lev based similarity
@functools.lru_cache
def lev_sim(str1: str, str2: str):
    max_len = max(len(str1), len(str2))
    return 1 - distance(str1, str2) / max_len


class Extractor:
    # essential params
    max_sentence_length: int = 300  # in characters
    max_translation_pairs: int = 0  # 500_000
    min_source_rep: int = 5  # minimum number of times a source term must appear in the target text to be considered a candidate
    max_source_rep: int = 30  # maximum number of times a source term can be counted (to avoid excessive computation)
    target_dismiss: int = 5  # if a target term does not appear after the source has occurred X times, the target will not be tracked or counted
    max_excel_cand_count: int = 25  # maximum number of top target candidates to include in the Excel report
    min_count_ratio: float = 0.4  # minimum ratio of target occurrences to source occurrences
    enable_partial_points: bool = False  # (experimental) Whether longer terms can gain partial points from high scoring shorter terms
    verbose_logging = False  # whether to include details about points gained

    # candidate count limits for different stages (for balancing accuracy vs. speed)
    max_1st_cleanup_cand_count: int = 200  # maximum number of top target candidates to keep after the first sorting and cleanup stage
    max_grouping_cand_count: int = 100  # maximum number of top target candidates to keep in memory after grouping roughly similar candidates
    max_llm_scoring_cand_count: int = 50  # maximum number of top target candidates to keep in memory after LLM-scoring and re-sorting

    # NLP
    n1: int = 1  # shortest n-gram to consider
    n2: int = 7  # longest n-gram to consider
    grouping_min_lev_sim: float = 0.7  # minimum Levenshtein score for grouping roughly similar target phrases token by token
    tok_min_lev_sim: float = 0.6  # parallel tokens needs to be at least this apart for their similarity to be counted. Any score below this is ignored (i.e., counted as 0)
    skip_peri_stop_words: bool = True  # skips ngrams that begin or end with stop words (saves computation and reduces false positives but misses phrasal verbs and phrasal nouns)
    skip_top_common_words: int = 10_000  # if > 0, skips top n words based on the library 'wordfreq'
    llm_scoring = True  # whether to do LLM scoring
    min_llm_score = 0.4  # minimum LLM score for cleanup
    src_term_extraction_method: str = "ngrams"  # ngrams or spacy
    model = 'LaBSE'

    # weighting params
    points_per_occurrence: int = 10  # points per occurrence
    llm_score_multiplier: int = 5_000  # LLM scores are multiplied by this number, and the result is added to the candidate points
    len_ratio_multiplier: int = 30  # length ratio is multiplied by this number, and the result is added to the candidate points
    points_per_slam_dunk: int = 10_000
    base_points_per_high_partial: int = 2  # (only if enable_partial_points == true) baseline points gained by longer phrases containing high-occurrence partial phrases. The baseline point gains are weighted by length ratio and occurrence ratio

    # general inits
    _src_lang: str = ""
    _tar_lang: str = ""
    _use_pred_src_terms: bool = False

    def __init__(self):
        self._tar_comm_words = None
        self._src_comm_words = None
        self._tar_sents = None  # for marking slam dunks (indexes of sentences where the entire segment is a term)
        self._src_sents = None  # for marking slam dunks (indexes of sentences where the entire segment is a term)
        self._tar_col = None
        self._src_col = None
        self._pred_terms = None
        self._cand_counts = {}
        self._report = {}

        #self._pred_terms_conn = None
        #self._pred_terms_cursor = None
        #self._pred_terms_db_file = None

    @staticmethod
    def _progress_msg(label: str, current: int, total: int):
        """Build a standardized progress dict."""
        pct = round((current / total) * 100, 2) if total > 0 else 0
        return {"type": "progress", "label": label, "current": current, "total": total, "pct": pct}

    def load_pred_src_terms(self, terms_txt_file: str):
        """
        Optional. Loads predefined source terms from a file.
        If used, source terms that are not found in this list will be excluded.
        Yields status dicts.
        """
        self._pred_terms = set()
        with open(terms_txt_file, newline='', mode='r', encoding='utf-8-sig') as f:
            for line in f:
                line = re.sub("[’‘´]", "'", line)  # normalize apostrophes
                self._pred_terms.add(line.lower().strip())
        self._use_pred_src_terms = True
        pred_terms_ct = len(self._pred_terms)
        yield {"type": "status", "message": f"Predefined terms loaded: {pred_terms_ct}"}

    @staticmethod
    def _count_csv_lines(csv_file: str):
        with open(csv_file, 'rb') as f:
            return sum(buf.count(b'\n') for buf in iter(lambda: f.read(1024 * 1024), b''))

    @staticmethod
    def _tok_count_ratio(src_str: str, tar_str: str):
        """
        Calculates the token count ratio between two strings (to assess how close in length they are).
        """
        nums = [len(src_str.split()), len(tar_str.split())]
        ratio = min(nums) / max(nums) if max(nums) != 0 else 0
        return ratio

    def _verify_lang_and_method_support(self):
        """
        Verifies that the source and target languages are supported by the selected methods.
        :return: Boolean. True if supported, False otherwise.
        """
        if self.src_term_extraction_method not in ['spacy', 'ngrams']:
            raise Exception(f"Invalid source term extraction method: '{self.src_term_extraction_method}'. Choose either 'spacy' or 'ngrams'.")

        if self.src_term_extraction_method == 'spacy' and self._src_lang not in SPACY_LANG_SUPPORT.keys():
            raise Exception(f"Spacy-based extraction is not available for the source language: '{self._src_lang}'.")

        if self._src_lang not in NLTK_LANG_SUPPORT.keys():
            raise Exception(f"NLTK-based extraction is not implemented for the source language: '{self._src_lang}'.")

        if self._tar_lang not in NLTK_LANG_SUPPORT.keys():
            raise Exception(f"NLTK-based extraction is not implemented for the target language: '{self._tar_lang}'.")

        if self._src_lang not in LABSE_LANG_SUPPORT.keys():
            raise Exception(f"LABSE-based encoding is not implemented for the source language: '{self._src_lang}'.")

        if self._tar_lang not in LABSE_LANG_SUPPORT.keys():
            raise Exception(f"LABSE-based encoding is not implemented for the target language: '{self._tar_lang}'.")

    def load_translations(self, csv_file: str, src_lang: str, tar_lang: str):
        """
        Loads translations from a csv file, creating a list of source and target ngrams for each translation pair.
        :param csv_file: Path of the csv file.
        :param src_lang: Source language code.
        :param tar_lang: Target language code.
        :return: Count of sentence pairs.
        """
        self._src_lang = src_lang
        self._tar_lang = tar_lang
        self._verify_lang_and_method_support()

        # unique_src = [] #md5 vals or src rows to avoid duplication
        rows_in_csv = Extractor._count_csv_lines(csv_file)
        pair_count = min([self.max_translation_pairs, rows_in_csv])
        yield {"type": "status", "message": f"CSV line count: {rows_in_csv}"}

        self._src_col = []  # List of lists. will collect sets of ngrams. [0] will hold the ngrams of the first source sentence. [1] will hold the ngrams of the second source sentence and so on.
        self._tar_col = []  # Same as above
        self._src_sents = []  # List of strings. Will collect sentences for the sake of tracking slam dunks (i.e., when the entire sentence is an ngram, i.e., a term)
        self._tar_sents = []  # Same as above
        self._src_comm_words = set()
        self._tar_comm_words = set()

        # prep common words
        if self.skip_top_common_words > 0:
            self._src_comm_words = set(top_n_list(self._src_lang, self.skip_top_common_words))
            self._tar_comm_words = set(top_n_list(self._tar_lang, self.skip_top_common_words))
            yield {"type": "status", "message": "Will exclude common words.."}

        skipped_rows = 0
        processed_rows = 0
        src_nlp = NLPTasks(src_lang, self.src_term_extraction_method)
        tar_nlp = NLPTasks(tar_lang)
        yield {"type": "step", "step": 0, "name": "Loading translations"}
        yield {"type": "status", "message": "Applying NLP to translations."}
        with open(csv_file, newline='', mode='r', encoding='utf-8-sig') as f:
            for pair in csv.reader(f, dialect="excel"):
                if len(pair) < 2:
                    continue
                if pair[0] == pair[1]:
                    processed_rows += 1
                    skipped_rows += 1
                    continue
                pair[0] = html.unescape(pair[0])
                pair[1] = html.unescape(pair[1])
                if len(pair[0]) > self.max_sentence_length or len(pair[1]) > self.max_sentence_length:  # skip long sentences
                    processed_rows += 1
                    skipped_rows += 1
                    continue
                # extract source terms based on the extraction method (spacy or ngrams)
                if self.src_term_extraction_method == 'ngrams':
                    temp_src_tok_phrases = src_nlp.tok_ngrams(pair[0], self.n1, self.n2, self.skip_peri_stop_words)
                elif self.src_term_extraction_method == 'spacy':
                    temp_src_tok_phrases = src_nlp.spacy_extract_terms(pair[0])

                # if known trams are enforced, match with them
                if self._use_pred_src_terms:
                    #src_tok_phrases = [phrase for phrase in temp_src_tok_phrases if phrase in self._pred_terms]
                    src_tok_phrases = {phrase for phrase in temp_src_tok_phrases if phrase.lower() in self._pred_terms}
                else:
                    src_tok_phrases = temp_src_tok_phrases

                # exclude source common words, if enforced
                if self.skip_peri_stop_words > 0:
                    src_tok_phrases = {phrase for phrase in src_tok_phrases if phrase.lower() not in self._src_comm_words}

                if len(src_tok_phrases) == 0:
                    processed_rows += 1
                    skipped_rows += 1
                    continue

                # now collect target phrases
                tar_tok_phrases = tar_nlp.tok_ngrams(pair[1], self.n1, self.n2, self.skip_peri_stop_words)
                # exclude target common words, if enforced
                if self.skip_peri_stop_words > 0:
                    tar_tok_phrases = {phrase for phrase in tar_tok_phrases if phrase.lower() not in self._tar_comm_words}

                if len(tar_tok_phrases) == 0:
                    processed_rows += 1
                    skipped_rows += 1
                    continue

                self._src_col.append(src_tok_phrases)
                self._tar_col.append(tar_tok_phrases)

                if processed_rows % 100 == 0:
                    yield Extractor._progress_msg("Translation pairs pre-processed", processed_rows, rows_in_csv)

                # for tracking slam dunks and sentence length
                self._src_sents.append(re.sub(f"[{src_nlp.puncts}]$", "", pair[0].lower().strip()))  # for tracking slam dunks
                self._tar_sents.append(re.sub(f"[{tar_nlp.puncts}]$", "", pair[1].lower().strip()))  # for tracking slam dunks
                processed_rows += 1
                if processed_rows >= self.max_translation_pairs != 0:
                    break

        yield Extractor._progress_msg("Translation pairs pre-processed", processed_rows, rows_in_csv)
        yield {"type": "status", "message": f"Skipped rows ({skipped_rows}): {skipped_rows / rows_in_csv * 100:.2f}%"}
        self._report.update({"total pairs": rows_in_csv, "processed": processed_rows, "skipped pairs": skipped_rows})

    def _prep_src_terms(self):
        """
        Counts source term candidates and drops those occurring below self.min_source_rep.
        TODO: consider merging source variants (acronyms, singulars & plurals)
        """
        yield {"type": "step", "step": 1, "name": "Preparing source terms"}
        src_terms = {}
        for index, src_phrase_list in enumerate(self._src_col):
            if index % 100 == 0:
                yield Extractor._progress_msg("Prepping source terms", index, len(self._src_col))
            for src_phrase in src_phrase_list:
                norm_src_phrase = src_phrase.lower()  # normalized src phrase
                sent_info = (index, len(self._src_sents[index]))  # sentence info (index, length). Shorter sentences will be prioritized later
                if src_terms.get(norm_src_phrase) is None:
                    src_terms[norm_src_phrase] = {"count": 1,  # the original total count; different from hits which can be capped
                                                  "original": src_phrase,
                                                  "cands": {},
                                                  "sent_info": [sent_info]  # sentence info (index,length)
                                                  }
                else:
                    src_terms[norm_src_phrase]["count"] += 1
                    src_terms[norm_src_phrase]["sent_info"].append(sent_info)

        self._cand_counts = {key: val for key, val in src_terms.items() if val["count"] >= self.min_source_rep}
        yield Extractor._progress_msg("Prepping source terms", len(self._src_col), len(self._src_col))

    def _pair_src_tar_terms(self):
        yield {"type": "step", "step": 2, "name": "Pairing source/target"}
        prog = 0
        src_count = len(self._cand_counts)
        for src_term, src_props in self._cand_counts.items():
            prog += 1
            self._parse_tar_candidates(src_term, src_props)
            if prog % 100 == 0:
                yield Extractor._progress_msg("Pairing", prog, src_count)

    def _parse_tar_candidates(self, src_phrase: str, src_props: dict):
        """
        For each provided source term, loops over the sentences where the source term is found, and analyzes potential target terms.
        """
        sent_info = sorted(src_props['sent_info'], key=lambda x: x[1])  # sort by the length of the sentence to prioritize shorter sentences
        src_hit_counter = 0
        for index, length in sent_info:  # loop based on sentence index and sentence length
            if src_hit_counter >= self.max_source_rep:
                return
            src_hit_counter += 1
            src_props['hits'] = src_hit_counter
            tar_cands = self._tar_col[index]
            for tar_phrase in tar_cands:
                # skip target terms that match the source term
                if tar_phrase.lower() == src_phrase:
                    continue
                both_slam_dunks = self._src_sents[index] == src_phrase and self._tar_sents[index] == tar_phrase.lower()

                if self._src_lang == "arabic" or self._tar_lang == "arabic":  # for Arabic, skip target segments containing the source segment (typical of acronyms)
                    if tar_phrase.lower() in src_phrase or src_phrase in tar_phrase.lower():
                        continue
                cand_tar_ref = src_props['cands'].get(tar_phrase)
                if cand_tar_ref is None and src_hit_counter >= self.target_dismiss:
                    #print(f"{tar_phrase} dismissed")
                    continue
                if cand_tar_ref is None:
                    src_props['cands'][tar_phrase] = {
                        "hits": 1,
                        "points": self.points_per_occurrence,
                        "occ_ratio": 1 / src_props['hits']
                    }
                    cand_tar_ref = src_props['cands'][tar_phrase]

                    # reward shortness
                    shortness_points = (1 / length) * 1000  # TODO: revise
                    cand_tar_ref["points"] += shortness_points

                    # reward length closeness
                    len_ratio = Extractor._tok_count_ratio(src_phrase, tar_phrase)
                    len_ratio_points = len_ratio * self.len_ratio_multiplier
                    cand_tar_ref["points"] += len_ratio_points
                    cand_tar_ref['len_ratio'] = len_ratio
                    if self.verbose_logging:
                        cand_tar_ref["points_log"] = []
                        cand_tar_ref["points_log"].append({"len_ratio_pts": len_ratio_points})
                        cand_tar_ref["points_log"].append({"occurrence_pts": self.points_per_occurrence})
                        cand_tar_ref["points_log"].append({"shortness_pts": shortness_points})
                else:
                    cand_tar_ref["hits"] += 1
                    cand_tar_ref["points"] += self.points_per_occurrence
                    cand_tar_ref["occ_ratio"] = cand_tar_ref["hits"] / src_props['hits']
                    if self.verbose_logging:
                        cand_tar_ref["points_log"].append({"occurrence_pts": self.points_per_occurrence})

                # handle slam dunks
                if both_slam_dunks:
                    cand_tar_ref['slam_dunk'] = True
                    cand_tar_ref["points"] += self.points_per_slam_dunk
                    if self.verbose_logging:
                        cand_tar_ref["points_log"].append({"slam_dunk_pts": self.points_per_slam_dunk})

    def _sort_tar_candidates(self):
        # sort and keep top N candidates
        yield {"type": "step", "step": 3, "name": "Sorting candidates"}
        ct = 0
        pairs_ct = len(self._cand_counts)
        for src_phrase in self._cand_counts:
            ct += 1
            self._cand_counts[src_phrase]['cands'] = dict(
                sorted(self._cand_counts[src_phrase]['cands'].items(), key=lambda key: key[1]["points"], reverse=True)[0:self.max_1st_cleanup_cand_count])
            if ct % 100 == 0:
                yield Extractor._progress_msg("Sorting target candidates", ct, pairs_ct)
        yield Extractor._progress_msg("Sorting target candidates", ct, pairs_ct)

    def _process_variants_and_partials(self, target_candidates: dict):
        grouped_tar_cands = {}
        for tar_phrase, tar_dets in target_candidates.items():
            # skip variants with count 0 (marked for ignoring) bkz they're already added
            if tar_dets.get("merged", False):
                continue

            grouped_tar_cands.update({tar_phrase: tar_dets.copy()})
            grouped_tar_cands[tar_phrase]["variants"] = []
            tar_dets['merged'] = True  # marked for ignoring since it's already added as a parent/variant
            # group potential fuzzy tar phrases under tar_phrase
            for pot_fuzzy_tar_phrase, pot_tar_phrase_dets in target_candidates.items():
                if tar_phrase == pot_fuzzy_tar_phrase:
                    continue  # will not add self as a fuzzy variant
                # next, apply lev sim as long as phrases have the same ngram count
                penalize_tok_shortness = True if len(tar_phrase.split()) == 1 == len(pot_fuzzy_tar_phrase.split()) else False  # TODO: OPTIMIZE
                fuzzy_sim = NLPTasks.lev_sim_tok_based(str1=tar_phrase, str2=pot_fuzzy_tar_phrase,
                                                       tok_min_lev_sim=self.tok_min_lev_sim,
                                                       force_equal_tok_count=True, penalize_shortness=penalize_tok_shortness)

                # swallow variants and inherit their points
                if fuzzy_sim >= self.grouping_min_lev_sim:
                    grouped_tar_cands[tar_phrase]['variants'].append({pot_fuzzy_tar_phrase: pot_tar_phrase_dets.copy()})
                    fuzzy_variant_points = pot_tar_phrase_dets['hits'] * self.points_per_occurrence
                    grouped_tar_cands[tar_phrase]['points'] += fuzzy_variant_points
                    grouped_tar_cands[tar_phrase]['earned_fuzzy'] = True
                    target_candidates[pot_fuzzy_tar_phrase]["merged"] = True
                    if self.verbose_logging:
                        grouped_tar_cands[tar_phrase]['points_log'].append({"fuzzy_variant_pts": fuzzy_variant_points})

                # (experimental) earn partial match points for long phrases that contain more or similarly frequent smaller phrases
                if self.enable_partial_points and pot_fuzzy_tar_phrase in tar_phrase and pot_tar_phrase_dets['occ_ratio'] > 0.6 and pot_tar_phrase_dets['hits'] >= \
                        grouped_tar_cands[tar_phrase]['hits']:
                    grouped_tar_cands[tar_phrase]['earned_partial'] = True
                    len_ratio = len(pot_fuzzy_tar_phrase) / len(tar_phrase)
                    partial_points = self.base_points_per_high_partial * pot_tar_phrase_dets['hits'] * pot_tar_phrase_dets['occ_ratio'] * len_ratio
                    grouped_tar_cands[tar_phrase]['points'] += partial_points
                    if self.verbose_logging:
                        grouped_tar_cands[tar_phrase]['points_log'].append({"partial_pts": partial_points})

        # return grouped_cands
        return dict(sorted(grouped_tar_cands.items(), key=lambda key: key[1]['points'], reverse=True)[0:self.max_grouping_cand_count])

    def _candidate_grouping(self):
        yield {"type": "step", "step": 4, "name": "Grouping variants"}
        ct = 0
        pairs_ct = len(self._cand_counts)
        for src_phrase in self._cand_counts:
            ct += 1
            self._cand_counts[src_phrase]['cands'] = self._process_variants_and_partials(self._cand_counts[src_phrase]['cands'])
            if not self.verbose_logging:
                self._cand_counts[src_phrase].pop('sent_info')
            if ct % 100 == 0:
                yield Extractor._progress_msg("Grouping", ct, pairs_ct)
        yield Extractor._progress_msg("Grouping", ct, pairs_ct)

    def _fetch_sorted_variants(self, main_variant: str, cand: dict):
        # finds the highest count variant among variants in a target candidate
        if len(cand['variants']) == 0:
            return [main_variant]
        all_variants = [{main_variant: cand}] + [variant for variant in cand['variants']]
        all_variants.sort(key=lambda x: list(x.values())[0]["hits"], reverse=True)
        return [next(iter(var_key.keys())) for var_key in all_variants]

    def _is_slam_dunk(self, src_dets: dict):
        if len(src_dets['cands']) == 0:
            return False
        first_tar_key = next(iter(src_dets['cands']))
        return src_dets['cands'][first_tar_key].get('slam_dunk', False)

    def _index_for_llm(self):
        yield {"type": "status", "message": "LLM indexing..."}
        self._temp_phrase_set = set()  # use this initially because it's much faster to add to a look up
        self._llm_phrase_index = None
        self._llm_embs = None
        cur_ct = 0
        total_ct = len(self._cand_counts)
        for left_val, left_info in self._cand_counts.items():
            cur_ct += 1
            #  skip slam dunks to preserve LLM computation
            # if self._is_slam_dunk(left_info):
            #     continue
            original_phrase = left_info['original']

            self._temp_phrase_set.add(original_phrase)
            if cur_ct % 100 == 0:
                yield Extractor._progress_msg("LLM indexing", cur_ct, total_ct)
            right_cands = self._cand_counts[left_val]['cands'].items()
            for right_val, right_info in right_cands:
                self._temp_phrase_set.add(right_val)
        yield Extractor._progress_msg("LLM indexing", cur_ct, total_ct)
        yield {"type": "status", "message": f"LLM embedding {len(self._temp_phrase_set)} phrases..."}
        self._llm_phrase_index = list(self._temp_phrase_set)
        del self._temp_phrase_set
        self.llm = LLMCompare(model=self.model)
        pool = self.llm.model.start_multi_process_pool()
        self._llm_embs = self.llm.model.encode(sentences=self._llm_phrase_index,
                                               normalize_embeddings=True,
                                               show_progress_bar=True,
                                               batch_size=64, pool=pool)

    def _score_with_llm(self):
        yield from self._index_for_llm()
        total_ct = len(self._cand_counts)
        cur_ct = 0
        yield {"type": "step", "step": 5, "name": "LLM Scoring"}
        for left_val, left_info in self._cand_counts.items():
            cur_ct += 1
            #  skip slam dunks to preserve LLM computation
            # if self._is_slam_dunk(left_info):
            #     continue
            original_phrase = left_info['original']
            if cur_ct % 100 == 0:
                yield Extractor._progress_msg("Scoring embeddings", cur_ct, total_ct)
            left_vec = self._llm_embs[self._llm_phrase_index.index(original_phrase)]
            right_cands = self._cand_counts[left_val]['cands'].items()
            for right_val, right_info in right_cands:
                right_vec = self._llm_embs[self._llm_phrase_index.index(right_val)]
                score = self.llm.sen_sim(left_vec, right_vec)
                right_info['llm_score'] = score
                llm_score_points = score * self.llm_score_multiplier
                right_info['points'] += llm_score_points
                if self.verbose_logging:
                    right_info['points_log'].append({"llm_score_pts": llm_score_points})
            self._cand_counts[left_val]['cands'] = dict(sorted(right_cands, key=lambda key: key[1]['points'], reverse=True)[0:self.max_llm_scoring_cand_count])
        yield Extractor._progress_msg("Scoring embeddings", cur_ct, total_ct)

    def _flag_low_scoring_src_terms(self):
        # sort and clean up to N top candidates
        yield {"type": "step", "step": 6, "name": "Final cleanup"}
        self._low_scoring_src_terms = []
        ct = 0
        pairs_ct = len(self._cand_counts)
        for src_phrase, src_dets in self._cand_counts.items():
            ct += 1
            first_tar = next(iter(src_dets['cands'].values()), None)
            if not first_tar:
                yield {"type": "status", "message": f"No TARGET CANDIDATES FOR '{src_phrase}'"}
                continue
            #first_tar = src_dets['cands'][next(iter(src_dets['cands'].keys()))]
            # mark candidates not scoring high enough (must fulfil 2 or more conditions to fail)
            if first_tar.get('llm_score', 0) < self.min_llm_score and first_tar['occ_ratio'] < self.min_count_ratio and self._is_slam_dunk(src_dets) is False:
                self._low_scoring_src_terms.append(src_phrase)
                src_dets['low_score'] = True
            if ct % 100 == 0:
                yield Extractor._progress_msg("Cleanup", ct, pairs_ct)
        yield Extractor._progress_msg("Cleanup", ct, pairs_ct)

    def _save_excel(self, file_name: str):
        """
        Save data to Excel with validation values from a separate sheet.
        """
        wb = Workbook()
        # ws stands for worksheet
        terms_ws = wb.active
        terms_ws.title = "Terms"

        # Create a separate sheet for validation values
        val_ws = wb.create_sheet(title="Options")

        # Setup headers in main sheet
        validation_cols = [f'option {i + 1}' for i in range(self.max_excel_cand_count)]
        val_ws.append(validation_cols)
        terms_ws.append([self._src_lang, self._tar_lang])
        # Populate data and validation sheet
        for ct, src_phrase in enumerate(self._cand_counts):
            # gets variants as list of lists
            all_variants = [
                #self._heighest_count_variant(tar_key, tar_dict)
                self._fetch_sorted_variants(tar_key, tar_dict)
                for tar_key, tar_dict in self._cand_counts[src_phrase]['cands'].items()
            ]

            # flatten the list of lists of variants
            tars = [item for sublist in all_variants for item in sublist][0:self.max_excel_cand_count]
            if len(tars) < 1:
                continue
            # Add data to main sheet
            terms_ws.append([self._cand_counts[src_phrase]['original'], tars[0]])

            # Add validation options to validation sheet
            val_ws.append(tars)

            if ct > 0:
                # Create data validation referencing the validation sheet
                # Reference format: 'SheetName'!$A$1:$O$1
                end_col = chr(65 + len(tars) - 1)  # Convert to column letter (A, B, C, etc.)
                formula = f"Options!$A${ct + 1}:${end_col}${ct + 1}"
                dv = DataValidation(type="list", formula1=formula, allow_blank=True)
                terms_ws.add_data_validation(dv)
                dv.add(f"B{ct + 1}")

        wb.save(file_name)

    def match_terms(self, tar_excel: str, json_report: bool = False, html_editor: bool = False, exp_low_score_list: bool = False):
        report = {}
        yield from self._prep_src_terms()
        yield from self._pair_src_tar_terms()

        # discard no-longer necessary lists
        del self._src_col
        del self._tar_col
        del self._src_sents
        del self._tar_sents

        yield from self._sort_tar_candidates()

        yield from self._candidate_grouping()
        if self.llm_scoring:
            yield from self._score_with_llm()
        yield from self._flag_low_scoring_src_terms()

        # remove low-scoring terms
        for low_score_term in self._low_scoring_src_terms:
            self._cand_counts.pop(low_score_term)
        yield {"type": "status", "message": f"Cleanup removed {len(self._low_scoring_src_terms)} low-scoring pairs."}
        self._report['terms count'] = len(self._cand_counts)
        self._report['excluded terms'] = len(self._low_scoring_src_terms)

        if json_report:
            unique_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
            terms_info = {"src_lang": self._src_lang,
                          "tar_lang": self._tar_lang,
                          "src_count": len(self._cand_counts),
                          "unique_id": unique_id,
                          "terms": self._cand_counts
                          }
            # save a full report including low-scoring terms
            with open(Path(tar_excel).with_suffix('.json'), "w", encoding='utf-8') as outfile:
                json.dump(terms_info, outfile, ensure_ascii=False)
                yield {"type": "status", "message": f"Total terms exported: {len(self._cand_counts)}"}

        if html_editor:
            dest_file = Path(tar_excel).parent / "edit-terms.html"
            with importlib.resources.path("term_extractor", "edit-terms.html") as src_path:
                shutil.copy(src_path, dest_file)

        if exp_low_score_list:
            with open(Path(tar_excel).with_suffix('_with_low_scores.txt'), "w", encoding='utf-8') as outfile:
                outfile.write("\n".join(self._low_scoring_src_terms))
                outfile.close()

        self._save_excel(tar_excel)
        yield {"type": "result", "data": self._report}


if __name__ == '__main__':
    pass
